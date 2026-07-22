import subprocess
from pathlib import Path

import httpx
import pytest
from gitlab import GitlabError

from codespace import shared
from codespace.client import service
from codespace.client.config import AgentProfile, DefaultsConfig, WebConfig
from codespace.client.service import SshHttpTunnel, _agent_target_host, _ssh_forward_target_host


def _profile(**overrides: object) -> AgentProfile:
    base: dict[str, object] = {
        "id": "home",
        "agent_url": "http://agent",
        "ssh_host": "10.0.0.5",
    }
    base.update(overrides)
    return AgentProfile(**base)  # type: ignore[arg-type]


def _service(*profiles: AgentProfile) -> service.CodespaceService:
    agents = {profile.id: profile for profile in (profiles or (_profile(),))}
    default = next(iter(agents))
    cfg = WebConfig(defaults=DefaultsConfig(agent=default, image="img"), agents=agents)
    return service.CodespaceService(cfg)


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
        deploy_public_key="ssh-ed25519 PUB",
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


# --- request() -------------------------------------------------------------


def test_request_wraps_transport_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(service.httpx, "request", _raise)

    with pytest.raises(service.ServiceError, match="cannot reach agent: refused"):
        service.request("GET", "http://agent/codespaces")


def test_request_parses_json_body(monkeypatch: pytest.MonkeyPatch) -> None:
    def _ok(method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(service.httpx, "request", _ok)

    assert service.request("GET", "http://agent/x") == (200, {"ok": True})


def test_request_returns_empty_dict_for_no_content(monkeypatch: pytest.MonkeyPatch) -> None:
    def _empty(method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(204)

    monkeypatch.setattr(service.httpx, "request", _empty)

    assert service.request("DELETE", "http://agent/x") == (204, {})


def test_request_falls_back_to_text_for_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def _text(method: str, url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    monkeypatch.setattr(service.httpx, "request", _text)

    assert service.request("GET", "http://agent/x") == (502, {"error": "bad gateway"})


# --- agent_error() ---------------------------------------------------------


def test_agent_error_uses_explicit_error_field() -> None:
    assert service.agent_error({"error": "boom"}, 500) == "boom"


def test_agent_error_defaults_when_no_detail() -> None:
    assert service.agent_error({}, 503) == "agent returned HTTP 503"


def test_agent_error_handles_non_dict_payload() -> None:
    assert service.agent_error(["nope"], 500) == "agent returned HTTP 500"


def test_agent_error_formats_string_detail() -> None:
    assert service.agent_error({"detail": "plain reason"}, 400) == (
        "agent returned HTTP 400: plain reason"
    )


# --- login key lifecycle ---------------------------------------------------


def test_ensure_login_key_generates_and_reuses_keypair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "KEY_DIR", tmp_path)
    calls: list[list[str]] = []

    def _run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        key_path = Path(cmd[cmd.index("-f") + 1])
        if cmd[1] == "-t":  # keygen: write both halves
            key_path.write_text("PRIVATE\n")
            key_path.with_suffix(".pub").write_text("ssh-ed25519 PUB\n")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "ssh-ed25519 PUB", "")

    monkeypatch.setattr(service.subprocess, "run", _run)

    first = service.ensure_login_key("home-api-dev")
    assert first == "ssh-ed25519 PUB"
    assert (tmp_path / "home-api-dev").exists()

    # A second call with the key already present must not re-run ssh-keygen.
    calls.clear()
    second = service.ensure_login_key("home-api-dev")
    assert second == "ssh-ed25519 PUB"
    assert calls == []


def test_ensure_login_key_treats_empty_private_key_as_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "KEY_DIR", tmp_path)
    (tmp_path / "home-api-dev").write_text("")  # 0-byte stale key

    def _run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        key_path = Path(cmd[cmd.index("-f") + 1])
        key_path.write_text("PRIVATE\n")
        key_path.with_suffix(".pub").write_text("ssh-ed25519 REGEN\n")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(service.subprocess, "run", _run)

    assert service.ensure_login_key("home-api-dev") == "ssh-ed25519 REGEN"


def test_remove_login_key_deletes_both_halves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "KEY_DIR", tmp_path)
    (tmp_path / "alias").write_text("PRIV")
    (tmp_path / "alias.pub").write_text("PUB")

    service.remove_login_key("alias")

    assert not (tmp_path / "alias").exists()
    assert not (tmp_path / "alias.pub").exists()
    # Idempotent: removing an already-absent key must not raise.
    service.remove_login_key("alias")


# --- revoke_quietly --------------------------------------------------------


def test_revoke_quietly_swallows_provider_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeProvider:
        def delete_deploy_key(self, *args: object, **kwargs: object) -> bool:
            raise GitlabError("403")

    monkeypatch.setattr(service, "provider_client", lambda provider: FakeProvider())

    # Must not raise despite the provider error.
    service.revoke_quietly("tok", "owner/name", "abc123", provider="gitlab")


# --- agent()/list helpers --------------------------------------------------


def test_agent_rejects_unknown_id() -> None:
    with pytest.raises(service.ServiceError, match="unknown agent: ghost"):
        _service().agent("ghost")


def test_list_agent_codespaces_reports_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service()
    monkeypatch.setattr(
        service.CodespaceService,
        "request_agent",
        lambda *a, **k: (500, {"error": "podman down"}),
    )

    result = svc.list_agent_codespaces("home")

    assert result.online is False
    assert result.error == "podman down"


def test_list_agent_codespaces_rejects_non_list_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service()
    monkeypatch.setattr(
        service.CodespaceService, "request_agent", lambda *a, **k: (200, {"not": "a list"})
    )

    result = svc.list_agent_codespaces("home")

    assert result.online is False
    assert result.error == "agent returned non-list response"


def test_list_agent_codespaces_converts_exceptions_to_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service()

    def _boom(*a: object, **k: object) -> tuple[int, object]:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(service.CodespaceService, "request_agent", _boom)

    result = svc.list_agent_codespaces("home")

    assert result.online is False
    assert result.error == "kaboom"


def test_list_all_agents_preserves_config_order(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service(_profile(id="home"), _profile(id="office", agent_url="http://office"))

    def _list(self: service.CodespaceService, agent_id: str) -> service.AgentListResult:
        return service.AgentListResult(agent=self.agent(agent_id), online=True)

    monkeypatch.setattr(service.CodespaceService, "list_agent_codespaces", _list)

    results = svc.list_all_agents()

    assert [r.agent.id for r in results] == ["home", "office"]


def test_agent_base_url_returns_direct_url_without_proxy() -> None:
    svc = _service(_profile(id="home", agent_url="http://direct:8001"))

    assert svc._agent_base_url(svc.agent("home")) == "http://direct:8001"


# --- wait_create_operation -------------------------------------------------


def _op_response(status: str, **extra: object) -> dict[str, object]:
    return {"id": "op123", "status": status, "stage": status, **extra}


def test_wait_create_operation_returns_codespace_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service()
    profile = svc.agent("home")
    cs = shared.Codespace(
        id="abc123",
        port=49207,
        user="dev",
        container_id="cid",
        repo="owner/name",
        template="default",
        instance="default",
        workspace_dir="ws",
    )
    monkeypatch.setattr(
        service.CodespaceService,
        "request_agent",
        lambda *a, **k: (200, _op_response("succeeded", codespace=cs.model_dump())),
    )
    stages: list[str] = []

    result = svc.wait_create_operation(profile, "op123", progress=stages.append)

    assert result == cs
    assert stages == ["agent: succeeded"]


def test_wait_create_operation_raises_when_codespace_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service()
    monkeypatch.setattr(
        service.CodespaceService,
        "request_agent",
        lambda *a, **k: (200, _op_response("succeeded")),
    )

    with pytest.raises(service.ServiceError, match="without returning a codespace"):
        svc.wait_create_operation(svc.agent("home"), "op123")


def test_wait_create_operation_propagates_agent_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service()
    monkeypatch.setattr(
        service.CodespaceService,
        "request_agent",
        lambda *a, **k: (200, _op_response("failed", error="build blew up")),
    )

    with pytest.raises(service.ServiceError, match="build blew up"):
        svc.wait_create_operation(svc.agent("home"), "op123")


def test_wait_create_operation_times_out_while_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service()
    monkeypatch.setattr(service, "_poll_retry", lambda *_a: _fast_poll_retry())
    monkeypatch.setattr(
        service.CodespaceService,
        "request_agent",
        lambda *a, **k: (200, _op_response("running")),
    )

    with pytest.raises(service.ServiceError, match="timed out"):
        svc.wait_create_operation(svc.agent("home"), "op123")


def _fast_poll_retry() -> "service.Retrying":
    from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed

    return Retrying(
        stop=stop_after_attempt(2),
        wait=wait_fixed(0),
        retry=retry_if_exception_type(service._OperationPending),
        reraise=True,
    )


# --- clone_remote_repo -----------------------------------------------------


def test_clone_remote_repo_succeeds_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service()
    monkeypatch.setattr(
        service.CodespaceService, "request_agent", lambda *a, **k: (200, {"ok": True})
    )

    # Returns without raising.
    svc.clone_remote_repo(svc.agent("home"), "abc123")


def test_clone_remote_repo_raises_after_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed

    svc = _service()
    attempts = 0

    def _request_agent(*a: object, **k: object) -> tuple[int, dict]:
        nonlocal attempts
        attempts += 1
        return 503, {"error": "workspace not mounted yet"}

    monkeypatch.setattr(
        service,
        "_clone_retry",
        lambda: Retrying(
            stop=stop_after_attempt(3),
            wait=wait_fixed(0),
            retry=retry_if_exception_type(service._CloneNotReady),
            reraise=True,
        ),
    )
    monkeypatch.setattr(service.CodespaceService, "request_agent", _request_agent)

    with pytest.raises(service.ServiceError, match="workspace not mounted yet"):
        svc.clone_remote_repo(svc.agent("home"), "abc123")
    assert attempts == 3


# --- create_codespace rollback ---------------------------------------------


def test_create_codespace_rolls_back_after_clone_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service()
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
        deploy_public_key="ssh-ed25519 PUB",
    )

    monkeypatch.setattr(service, "ensure_login_key", lambda alias: "ssh-ed25519 LOGIN")
    monkeypatch.setattr(service.CodespaceService, "wait_create_operation", lambda *a, **k: cs)

    class FakeProvider:
        def register_deploy_key(self, *args: object, **kwargs: object) -> int:
            events.append("register")
            return 1

    monkeypatch.setattr(service, "provider_client", lambda provider: FakeProvider())
    monkeypatch.setattr(service, "revoke_quietly", lambda *a, **k: events.append("revoke"))
    monkeypatch.setattr(service, "remove_login_key", lambda alias: events.append("remove-key"))
    monkeypatch.setattr(
        service.CodespaceService,
        "delete_remote",
        lambda self, profile, cs_id, **k: events.append(f"delete-remote:{cs_id}"),
    )

    def _clone(self: service.CodespaceService, profile: AgentProfile, cs_id: str) -> None:
        events.append("clone")
        raise service.ServiceError("clone exploded")

    monkeypatch.setattr(service.CodespaceService, "clone_remote_repo", _clone)

    def _request_agent(*a: object, **k: object) -> tuple[int, dict]:
        return 202, _op_response("queued")

    monkeypatch.setattr(service.CodespaceService, "request_agent", _request_agent)

    with pytest.raises(service.ServiceError, match="clone exploded"):
        svc.create_codespace(
            "home",
            service.CreateCodespaceInput(repo="owner/name", image="img"),
            token="tok",
        )

    # Deploy key registered before the failure must be revoked, the remote
    # container torn down, and the local login key cleaned up.
    assert events == ["register", "clone", "revoke", "delete-remote:abc123", "remove-key"]


def test_create_codespace_requires_deploy_public_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service()
    cs = shared.Codespace(
        id="abc123",
        port=49207,
        user="dev",
        container_id="cid",
        repo="owner/name",
        template="default",
        instance="default",
        workspace_dir="ws",
    )
    monkeypatch.setattr(service, "ensure_login_key", lambda alias: "LOGIN")
    monkeypatch.setattr(service.CodespaceService, "wait_create_operation", lambda *a, **k: cs)
    monkeypatch.setattr(service, "remove_login_key", lambda alias: None)
    monkeypatch.setattr(
        service.CodespaceService, "delete_remote", lambda self, profile, cs_id, **k: None
    )
    monkeypatch.setattr(
        service.CodespaceService, "request_agent", lambda *a, **k: (202, _op_response("queued"))
    )

    with pytest.raises(service.ServiceError, match="deploy public key"):
        svc.create_codespace(
            "home",
            service.CreateCodespaceInput(repo="owner/name", image="img"),
            token="tok",
        )


# --- delete_codespace warning branches -------------------------------------


def test_delete_codespace_warns_when_token_present_but_repo_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service()
    monkeypatch.setattr(service.ssh_config, "find_entry", lambda **kwargs: None)
    monkeypatch.setattr(
        service.CodespaceService,
        "delete_remote",
        lambda self, profile, cs_id, **k: shared.DeleteResponse(ok=True, workspace_removed=False),
    )

    result = svc.delete_codespace("home", "abc123", token="tok", repo=None)

    assert result.ok is True
    assert result.warning is not None
    assert "repo metadata is missing" in result.warning


def test_delete_codespace_warns_and_cleans_local_when_token_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = _service()
    events: list[str] = []
    entry = service.ssh_config.SshConfigEntry(
        alias="home-api-dev", codespace_id="abc123", agent_id="home", repo="owner/name"
    )
    monkeypatch.setattr(service.ssh_config, "find_entry", lambda **kwargs: entry)
    monkeypatch.setattr(
        service.ssh_config, "remove", lambda alias: events.append(f"ssh-remove:{alias}")
    )
    monkeypatch.setattr(service, "remove_login_key", lambda alias: events.append(f"key:{alias}"))
    monkeypatch.setattr(
        service.CodespaceService,
        "delete_remote",
        lambda self, profile, cs_id, **k: shared.DeleteResponse(ok=True, workspace_removed=True),
    )

    result = svc.delete_codespace("home", "abc123", token=None)

    assert result.warning is not None
    assert "token is not available" in result.warning
    # Local alias and login key are cleaned up even without a token.
    assert events == ["ssh-remove:home-api-dev", "key:home-api-dev"]
