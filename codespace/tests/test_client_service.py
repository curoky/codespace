import subprocess

import pytest

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
    monkeypatch.setattr(
        service.github, "register_deploy_key", lambda *a, **k: events.append("register")
    )
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
            return 202, {"id": "op123", "status": "queued", "stage": "queued"}
        if method == "POST" and path == "/codespaces/abc123/clone":
            events.append("clone")
            return 200, {"ok": True}
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(service.CodespaceService, "request_agent", _request_agent)

    result = svc.create_codespace(
        "home",
        service.CreateCodespaceInput(
            repo="owner/name", template="api", instance="dev", image="img"
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
                    "loc": ["body", "template"],
                    "msg": "Extra inputs are not permitted",
                    "input": "api",
                }
            ]
        },
        422,
    )

    assert "body.template: Extra inputs are not permitted" in message
    assert "running agent is using the old create API" in message
