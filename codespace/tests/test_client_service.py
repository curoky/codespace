import subprocess

import pytest
from gitlab import GitlabError

from codespace import shared
from codespace.client import service
from codespace.client.config import AgentProfile, DefaultsConfig, WebConfig
from codespace.client.service import SshHttpTunnel, _agent_target_host, _ssh_forward_target_host


def test_ssh_forward_target_host_wraps_ipv6_addresses() -> None:
    assert (
        _ssh_forward_target_host("2605:340:cd52:105:3634:f427:f62d:4143")
        == "[2605:340:cd52:105:3634:f427:f62d:4143]"
    )


def test_ssh_forward_target_host_leaves_non_ipv6_hosts_unchanged() -> None:
    assert _ssh_forward_target_host("127.0.0.1") == "127.0.0.1"
    assert _ssh_forward_target_host("agent.internal") == "agent.internal"


def test_agent_target_host_maps_ipv6_wildcard_to_loopback() -> None:
    assert _agent_target_host("::") == "127.0.0.1"


def test_ssh_http_tunnel_uses_distinct_proxy_host(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    class FakeProcess:
        def poll(self) -> None:
            return None

    def _popen(cmd: list[str], **kwargs: object) -> FakeProcess:
        commands.append(cmd)
        assert kwargs["stdout"] is subprocess.PIPE
        assert kwargs["stderr"] is subprocess.PIPE
        return FakeProcess()

    monkeypatch.setattr("codespace.client.service._free_local_port", lambda: 43210)
    monkeypatch.setattr("codespace.client.service._wait_for_agent", lambda _url: None)
    monkeypatch.setattr("codespace.client.service.subprocess.Popen", _popen)

    tunnel = SshHttpTunnel(
        AgentProfile(
            id="home",
            agent_url="http://127.0.0.1:8001",
            ssh_host="dev-container-host",
            ssh_proxy_host="bastion-host",
            ssh_proxy=True,
        )
    )

    assert tunnel.local_url == "http://127.0.0.1:43210"
    assert commands == [
        [
            "ssh",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=2",
            "-N",
            "-L",
            "127.0.0.1:43210:127.0.0.1:8001",
            "bastion-host",
        ]
    ]


def test_create_codespace_clones_after_registering_deploy_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = AgentProfile(id="home", agent_url="http://agent", ssh_host="10.0.0.5")
    cfg = WebConfig(defaults=DefaultsConfig(agent="home", image="img"), agents={"home": profile})
    svc = service.CodespaceService(cfg)
    events: list[str] = []
    cs = shared.Codespace(
        id="abc123",
        port=49207,
        user="dev",
        container_id="cid",
        repo="owner/name",
        template="default",
        instance="default",
        workspace_dir="ws",
        deploy_keys=[
            shared.DeployKeyRef(
                repo="owner/name", public_openssh="ssh-ed25519 PUB", read_only=False
            )
        ],
    )

    monkeypatch.setattr(service, "ensure_login_key", lambda alias: "ssh-ed25519 LOGIN")

    class FakeProvider:
        def register_deploy_key(self, *args: object, **kwargs: object) -> int:
            events.append("register")
            return 1

    monkeypatch.setattr(service, "provider_client", lambda provider: FakeProvider())
    monkeypatch.setattr(service.ssh_config, "upsert", lambda *a, **k: events.append("upsert"))
    monkeypatch.setattr(service.CodespaceService, "wait_create_operation", lambda *a, **k: cs)

    def _request_agent(
        self: service.CodespaceService,
        request_profile: AgentProfile,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        timeout: float = service.HTTP_TIMEOUT,
    ) -> tuple[int, dict]:
        assert request_profile == profile
        if method == "POST" and path == "/codespaces":
            events.append("create")
            assert body is not None
            assert "env" not in body
            return 202, {"id": "op123", "status": "queued", "stage": "queued"}
        if method == "POST" and path == "/codespaces/abc123/clone":
            assert timeout == service.CLONE_HTTP_TIMEOUT
            events.append("clone")
            return 200, {"ok": True}
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(service.CodespaceService, "request_agent", _request_agent)

    result = svc.create_codespace(
        "home",
        service.CreateCodespaceInput(
            repo="owner/name",
            template="api",
            instance="dev",
            image="img",
        ),
        token="tok",
    )

    assert result == cs
    assert events == ["create", "register", "clone", "upsert"]


def test_instance_alias_uses_agent_template_and_instance() -> None:
    assert service.instance_alias("home", "api", "dev") == "home-api-dev"


def test_agent_error_renders_validation_detail() -> None:
    message = service.agent_error(
        {
            "detail": [
                {
                    "type": "extra_forbidden",
                    "loc": ["body", "image"],
                    "msg": "Field required",
                    "input": "api",
                }
            ]
        },
        422,
    )

    assert "body.image: Field required" in message


def test_delete_codespace_continues_when_deploy_key_revocation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = AgentProfile(id="home", agent_url="http://agent", ssh_host="10.0.0.5")
    cfg = WebConfig(defaults=DefaultsConfig(agent="home", image="img"), agents={"home": profile})
    svc = service.CodespaceService(cfg)
    events: list[str] = []

    class FakeProvider:
        display_name = "GitLab"

        def delete_deploy_key(self, token: str, repo: str, cs_id: str) -> bool:
            assert token == "tok"
            assert repo == "group/project"
            assert cs_id == "abc123"
            events.append("delete-key")
            raise GitlabError("403: insufficient_granular_scope")

    def _request_agent(
        self: service.CodespaceService,
        request_profile: AgentProfile,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        timeout: float = service.HTTP_TIMEOUT,
    ) -> tuple[int, dict]:
        assert request_profile == profile
        assert method == "DELETE"
        assert path == "/codespaces/abc123?purge=true"
        events.append("delete-remote")
        return 200, {"ok": True, "workspace_removed": True}

    monkeypatch.setattr(service, "provider_client", lambda provider: FakeProvider())
    monkeypatch.setattr(service.ssh_config, "find_entry", lambda **kwargs: None)
    monkeypatch.setattr(service.CodespaceService, "request_agent", _request_agent)

    result = svc.delete_codespace(
        "home",
        "abc123",
        token="tok",
        repo="group/project",
        provider="gitlab",
        purge=True,
    )

    assert events == ["delete-remote", "delete-key"]
    assert result.ok is True
    assert result.workspace_removed is True
    assert result.warning is not None
    assert "GitLab deploy key revocation failed for group/project" in result.warning
    assert "403: insufficient_granular_scope" in result.warning


def test_delete_codespace_does_not_revoke_key_when_remote_delete_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = AgentProfile(id="home", agent_url="http://agent", ssh_host="10.0.0.5")
    cfg = WebConfig(defaults=DefaultsConfig(agent="home", image="img"), agents={"home": profile})
    svc = service.CodespaceService(cfg)
    events: list[str] = []

    class FakeProvider:
        def delete_deploy_key(self, *args: object, **kwargs: object) -> bool:
            events.append("delete-key")
            return True

    def _request_agent(
        self: service.CodespaceService,
        request_profile: AgentProfile,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        timeout: float = service.HTTP_TIMEOUT,
    ) -> tuple[int, dict]:
        events.append("delete-remote")
        return 500, {"error": "podman unavailable"}

    monkeypatch.setattr(service, "provider_client", lambda provider: FakeProvider())
    monkeypatch.setattr(service.ssh_config, "find_entry", lambda **kwargs: None)
    monkeypatch.setattr(service.CodespaceService, "request_agent", _request_agent)

    with pytest.raises(service.ServiceError, match="podman unavailable"):
        svc.delete_codespace(
            "home",
            "abc123",
            token="tok",
            repo="group/project",
            provider="gitlab",
        )

    assert events == ["delete-remote"]
