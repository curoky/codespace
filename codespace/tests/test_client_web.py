"""Tests for the local Web GUI FastAPI app."""

import time
from collections.abc import Callable
from typing import cast

import pytest
from fastapi.testclient import TestClient

from codespace import shared
from codespace.client import web, web_projection
from codespace.client.config import (
    AgentProfile,
    CreateTemplateConfig,
    DefaultsConfig,
    WebConfig,
)
from codespace.client.web_models import CreateCodespaceRequest
from codespace.client.web_operations import OperationStore


def _config() -> WebConfig:
    return WebConfig(
        defaults=DefaultsConfig(agent="home", image="img"),
        agents={
            "home": AgentProfile(id="home", agent_url="http://home:8001", ssh_host="10.0.0.5"),
            "office": AgentProfile(
                id="office",
                agent_url="http://office:8001",
                ssh_host="10.0.0.8",
                ssh_proxy_host="office-bastion",
                ssh_proxy=True,
            ),
        },
        templates={
            "api": CreateTemplateConfig(
                id="api",
                description="Backend service environment",
                agent="office",
                repo="owner/api",
                image="custom-img",
            )
        },
    )


def _codespace() -> shared.Codespace:
    return shared.Codespace(
        id="abc123",
        port=49207,
        user="dev",
        container_id="cid",
        repo="owner/name",
        template="api",
        instance="dev",
        workspace_dir="ws",
        status="running",
    )


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(web, "load_config", lambda path=None: _config())
    return TestClient(web.create_app())


def test_config_does_not_include_tokens(app_client: TestClient) -> None:
    resp = app_client.get("/api/config")

    assert resp.status_code == 200
    body = resp.json()
    assert "github" not in body
    assert "gitlab" not in body
    assert "token" not in str(body)


def test_config_returns_create_templates(app_client: TestClient) -> None:
    resp = app_client.get("/api/config")

    assert resp.status_code == 200
    assert resp.json()["templates"] == [
        {
            "id": "api",
            "description": "Backend service environment",
            "agent": "office",
            "provider": "github",
            "repo": "owner/api",
            "image": "custom-img",
        }
    ]


def test_config_returns_agent_proxy_flag(app_client: TestClient) -> None:
    resp = app_client.get("/api/config")

    assert resp.status_code == 200
    assert resp.json()["agents"][0]["ssh_proxy"] is False
    assert resp.json()["agents"][0]["ssh_proxy_host"] is None
    assert resp.json()["agents"][1]["ssh_proxy"] is True
    assert resp.json()["agents"][1]["ssh_proxy_host"] == "office-bastion"


def test_static_page_and_script_are_served(app_client: TestClient) -> None:
    index = app_client.get("/")
    script = app_client.get("/static/js/main.js")

    assert index.status_code == 200
    assert "Codespace Dashboard" in index.text
    assert "data-mantine-color-scheme" in index.text
    assert "bulma" not in index.text
    assert "@primer/css" not in index.text
    assert "bootstrap" not in index.text
    assert script.status_code == 200
    assert "text/javascript" in script.headers["content-type"]
    assert "/api/config" in script.text
    assert "/api/dashboard" in script.text
    assert "root" in index.text
    assert "codespaces" in script.text
    assert "Templates" in script.text
    assert "Templates" in script.text
    assert "Create" in script.text


def test_dashboard_aggregates_agents(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codespace.client import service

    monkeypatch.setattr(
        service.CodespaceService,
        "list_all_agents",
        lambda self: [
            service.AgentListResult(
                agent=self.agent("home"), online=True, codespaces=[_codespace()]
            ),
            service.AgentListResult(agent=self.agent("office"), online=False, error="down"),
        ],
    )

    resp = app_client.get("/api/dashboard")

    assert resp.status_code == 200
    body = resp.json()
    assert body["agents"][0]["status"] == "online"
    assert body["agents"][1]["status"] == "offline"
    assert body["agents"][0]["ssh_host"] == "10.0.0.5"
    assert body["agents"][0]["ssh_proxy_host"] is None
    assert body["agents"][1]["ssh_host"] == "10.0.0.8"
    assert body["agents"][1]["ssh_proxy_host"] == "office-bastion"
    assert body["codespaces"][0]["raw_ssh_command"] == "ssh dev@10.0.0.5 -p 49207"
    assert body["codespaces"][0]["trae_url"] == (
        "trae://vscode-remote/ssh-remote+dev%4010.0.0.5%3A49207/workspace/name?"
        "windowId=_blank&fullscreen=true"
    )


def test_dashboard_does_not_prune_completed_operations(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codespace.client import service

    monkeypatch.setattr(service.CodespaceService, "list_all_agents", lambda self: [])
    token_resp = app_client.put("/api/provider-tokens/github", json={"token": "secret"})
    assert token_resp.status_code == 200

    def _create(
        self: service.CodespaceService,
        agent_id: str,
        req: service.CreateCodespaceInput,
        *,
        token: str,
        progress: Callable[[str], None] | None = None,
    ) -> shared.Codespace:
        return _codespace()

    monkeypatch.setattr(service.CodespaceService, "create_codespace", _create)
    resp = app_client.post(
        "/api/agents/home/codespaces",
        json={"repo": "owner/name", "template": "api", "instance": "dev", "image": "img"},
    )
    op_id = resp.json()["operation_id"]

    for _ in range(20):
        op = app_client.get(f"/api/operations/{op_id}").json()
        if op["status"] == "succeeded":
            break
        time.sleep(0.01)

    dashboard = app_client.get("/api/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["operations"][0]["id"] == op_id
    assert app_client.get(f"/api/operations/{op_id}").status_code == 200


def test_trae_url_defaults_to_workspace_without_repo() -> None:
    assert web_projection.trae_remote_ssh_url("dev@10.0.0.5:49207") == (
        "trae://vscode-remote/ssh-remote+dev%4010.0.0.5%3A49207/workspace?"
        "windowId=_blank&fullscreen=true"
    )


def test_trae_url_uses_repo_path_when_repo_is_specified() -> None:
    assert web_projection.trae_remote_ssh_url("dev@10.0.0.5:49207", repo="owner/api.git") == (
        "trae://vscode-remote/ssh-remote+dev%4010.0.0.5%3A49207/workspace/api?"
        "windowId=_blank&fullscreen=true"
    )


def test_trae_url_can_disable_new_window_hint() -> None:
    assert (
        web_projection.trae_remote_ssh_url("dev@10.0.0.5:49207", repo="owner/api", new_window=False)
        == "trae://vscode-remote/ssh-remote+dev%4010.0.0.5%3A49207/workspace/api?fullscreen=true"
    )


def test_trae_url_can_disable_fullscreen_hint() -> None:
    assert (
        web_projection.trae_remote_ssh_url("dev@10.0.0.5:49207", repo="owner/api", fullscreen=False)
        == "trae://vscode-remote/ssh-remote+dev%4010.0.0.5%3A49207/workspace/api?windowId=_blank"
    )


def test_operation_lifecycle(app_client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from codespace.client import service

    def _create(
        self: service.CodespaceService,
        agent_id: str,
        req: service.CreateCodespaceInput,
        *,
        token: str,
        progress: Callable[[str], None] | None = None,
    ) -> shared.Codespace:
        assert agent_id == "home"
        assert token == "secret"
        if progress:
            progress("testing")
        return _codespace()

    monkeypatch.setattr(service.CodespaceService, "create_codespace", _create)
    token_resp = app_client.put("/api/provider-tokens/github", json={"token": "secret"})
    assert token_resp.status_code == 200

    resp = app_client.post(
        "/api/agents/home/codespaces",
        json={
            "repo": "owner/name",
            "template": "api",
            "instance": "dev",
            "image": "img",
        },
    )
    assert resp.status_code == 200
    op_id = resp.json()["operation_id"]
    op: dict[str, object] = {}

    for _ in range(20):
        op = cast(dict[str, object], app_client.get(f"/api/operations/{op_id}").json())
        if op["status"] == "succeeded":
            break
        time.sleep(0.01)

    assert op["status"] == "succeeded"
    assert op["stage"] == "ready"


def test_create_requires_saved_provider_token(app_client: TestClient) -> None:
    resp = app_client.post(
        "/api/agents/home/codespaces",
        json={"repo": "owner/name", "template": "api", "instance": "dev", "image": "img"},
    )

    assert resp.status_code == 400
    assert resp.json() == {"error": "github token is not set"}


def test_delete_passes_optional_request_token(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codespace.client import service

    def _delete(
        self: service.CodespaceService,
        agent_id: str,
        codespace_id: str,
        *,
        token: str | None,
        alias: str | None = None,
        repo: str | None = None,
        provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER,
        purge: bool = False,
    ) -> service.DeleteCodespaceResult:
        assert agent_id == "home"
        assert codespace_id == "abc123"
        assert token == "secret"
        assert repo == "owner/name"
        assert provider == "github"
        assert purge is True
        assert alias is None
        return service.DeleteCodespaceResult(
            ok=True,
            workspace_removed=True,
            warning="GitHub token is not available; skipped deploy key revocation",
        )

    monkeypatch.setattr(service.CodespaceService, "delete_codespace", _delete)
    token_resp = app_client.put("/api/provider-tokens/github", json={"token": "secret"})
    assert token_resp.status_code == 200

    resp = app_client.delete(
        "/api/agents/home/codespaces/abc123?repo=owner/name&provider=github&purge=true"
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "workspace_removed": True,
        "warning": "GitHub token is not available; skipped deploy key revocation",
    }


def test_service_uses_ssh_proxy_for_agent_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    from codespace.client import service

    profile = AgentProfile(
        id="home",
        agent_url="http://127.0.0.1:8001",
        ssh_host="dev-container-host",
        ssh_proxy_host="bastion-host",
        ssh_proxy=True,
    )
    cfg = WebConfig(defaults=DefaultsConfig(agent="home", image="img"), agents={"home": profile})
    requested: list[tuple[str, str]] = []

    class FakeTunnel:
        def __init__(self, tunnel_profile: AgentProfile) -> None:
            assert tunnel_profile == profile
            self.local_url = "http://127.0.0.1:43210"

        def is_running(self) -> bool:
            return True

        def close(self) -> None:
            requested.append(("CLOSE", self.local_url))

    def _request(
        method: str, url: str, body: dict | None = None, *, timeout: float = service.HTTP_TIMEOUT
    ) -> tuple[int, list[dict[str, object]]]:
        requested.append((method, url))
        return 200, [_codespace().model_dump()]

    monkeypatch.setattr(service, "SshHttpTunnel", FakeTunnel)
    monkeypatch.setattr(service, "request", _request)

    svc = service.CodespaceService(cfg)
    result = svc.list_agent_codespaces("home")
    svc.close()

    assert result.online is True
    assert requested == [
        ("GET", "http://127.0.0.1:43210/codespaces"),
        ("CLOSE", "http://127.0.0.1:43210"),
    ]


def test_prune_completed_keeps_only_busy_operations() -> None:
    store = OperationStore()
    queued = store.create(
        agent_id="home",
        req=CreateCodespaceRequest(
            repo="curoky/devspace",
            template="api",
            instance="queued",
            image="ghcr.io/curoky/devspace:codespace-debian12",
        ),
    )
    failed = store.create(
        agent_id="home",
        req=CreateCodespaceRequest(
            repo="curoky/devspace",
            template="api",
            instance="failed",
            image="ghcr.io/curoky/devspace:codespace-debian12",
        ),
    )
    succeeded = store.create(
        agent_id="home",
        req=CreateCodespaceRequest(
            repo="curoky/devspace",
            template="api",
            instance="succeeded",
            image="ghcr.io/curoky/devspace:codespace-debian12",
        ),
    )

    store.update(failed.id, status="failed", stage="failed", error="boom")
    store.update(succeeded.id, status="succeeded", stage="ready")

    remaining = store.prune_completed()

    assert [operation.id for operation in remaining] == [queued.id]
    assert [operation.id for operation in store.list()] == [queued.id]


def test_prune_completed_older_than_keeps_recent_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    store = OperationStore()
    monkeypatch.setattr("codespace.client.web_operations.time.time", lambda: 100.0)
    old = store.create(
        agent_id="home",
        req=CreateCodespaceRequest(
            repo="curoky/devspace",
            template="api",
            instance="old",
            image="img",
        ),
    )
    recent = store.create(
        agent_id="home",
        req=CreateCodespaceRequest(
            repo="curoky/devspace",
            template="api",
            instance="recent",
            image="img",
        ),
    )
    store.update(old.id, status="failed", stage="failed")
    monkeypatch.setattr("codespace.client.web_operations.time.time", lambda: 200.0)
    store.update(recent.id, status="succeeded", stage="ready")
    monkeypatch.setattr("codespace.client.web_operations.time.time", lambda: 220.0)

    remaining = store.prune_completed_older_than(30.0)

    assert [operation.id for operation in remaining] == [recent.id]
