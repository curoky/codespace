"""Tests for the local Web GUI FastAPI app."""

import time
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from codespace import shared
from codespace.client import web
from codespace.client.config import (
    AgentProfile,
    CreateTemplateConfig,
    DefaultsConfig,
    GithubConfig,
    WebConfig,
)

INLINE_TEST_TOKEN = "github_pat_example"


def _config() -> WebConfig:
    return WebConfig(
        defaults=DefaultsConfig(agent="home", image="img"),
        github=GithubConfig(token_env="GITHUB_TOKEN"),
        agents={
            "home": AgentProfile(
                id="home", name="Home", agent_url="http://home:8001", ssh_host="10.0.0.5"
            ),
            "office": AgentProfile(
                id="office",
                name="Office",
                agent_url="http://office:8001",
                ssh_host="10.0.0.8",
            ),
        },
        templates={
            "api": CreateTemplateConfig(
                id="api",
                name="API Service",
                description="Backend service environment",
                agent="office",
                repo="owner/api",
                workspace="backend",
                alias="office-api-backend",
                image="custom-img",
                user="dev",
                extra_repos=["owner/shared"],
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
        workspace="default",
        workspace_dir="ws",
        status="running",
    )


@pytest.fixture
def app_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(web, "load_config", lambda path=None: _config())
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    return TestClient(web.create_app())


def test_config_hides_token(app_client: TestClient) -> None:
    resp = app_client.get("/api/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["github"] == {
        "token_env": "GITHUB_TOKEN",
        "has_token": True,
        "inline_token": False,
    }
    assert "secret" not in str(body)


def test_config_hides_inline_token(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config().model_copy(update={"github": GithubConfig(token_env=INLINE_TEST_TOKEN)})
    monkeypatch.setattr(web, "load_config", lambda path=None: config)
    app_client = TestClient(web.create_app())

    resp = app_client.get("/api/config")

    assert resp.status_code == 200
    body = resp.json()
    assert body["github"] == {
        "token_env": "inline GitHub credential",
        "has_token": True,
        "inline_token": True,
    }
    assert INLINE_TEST_TOKEN not in str(body)


def test_config_returns_create_templates(app_client: TestClient) -> None:
    resp = app_client.get("/api/config")

    assert resp.status_code == 200
    assert resp.json()["templates"] == [
        {
            "id": "api",
            "name": "API Service",
            "description": "Backend service environment",
            "agent": "office",
            "repo": "owner/api",
            "workspace": "backend",
            "alias": "office-api-backend",
            "image": "custom-img",
            "user": "dev",
            "extra_repos": ["owner/shared"],
        }
    ]


def test_static_page_and_script_are_served(app_client: TestClient) -> None:
    index = app_client.get("/")
    script = app_client.get("/static/js/main.js")

    assert index.status_code == 200
    assert "Codespace Dashboard" in index.text
    assert script.status_code == 200
    assert "text/javascript" in script.headers["content-type"]
    assert "await request('/api/config')" in script.text
    assert "Dashboard summary" in index.text
    assert "Dashboard navigation" not in index.text
    assert "app-sidebar" not in index.text
    assert "top-command-bar" in index.text
    assert "content-grid" in index.text
    assert "quick-template-select" in index.text
    assert "codespace-card-grid" in index.text
    assert "token-status-card" in index.text
    assert "status-filter" in index.text
    assert "auto-refresh-toggle" in index.text
    assert "Create Templates" in index.text
    assert "template-list" in index.text
    assert "filteredCodespaces" in script.text
    assert "scheduleAutoRefresh" in script.text
    assert "showToast" in script.text
    assert "renderTemplates" in script.text
    assert "renderQuickTemplates" in script.text
    assert "handleCodespaceAction" in script.text
    assert "openCreateFromTemplate" in script.text


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
    assert body["codespaces"][0]["raw_ssh_command"] == "ssh dev@10.0.0.5 -p 49207"


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

    resp = app_client.post(
        "/api/agents/home/codespaces",
        json={"repo": "owner/name", "alias": "home-name-default", "image": "img"},
    )
    assert resp.status_code == 200
    op_id = resp.json()["operation_id"]

    for _ in range(20):
        op = app_client.get(f"/api/operations/{op_id}").json()
        if op["status"] == "succeeded":
            break
        time.sleep(0.01)

    assert op["status"] == "succeeded"
    assert op["codespace"]["id"] == "abc123"


def test_create_accepts_inline_token_for_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codespace.client import service

    config = _config().model_copy(update={"github": GithubConfig(token_env=INLINE_TEST_TOKEN)})
    monkeypatch.setattr(web, "load_config", lambda path=None: config)

    def _create(
        self: service.CodespaceService,
        agent_id: str,
        req: service.CreateCodespaceInput,
        *,
        token: str,
        progress: Callable[[str], None] | None = None,
    ) -> shared.Codespace:
        assert token == INLINE_TEST_TOKEN
        return _codespace()

    monkeypatch.setattr(service.CodespaceService, "create_codespace", _create)
    app_client = TestClient(web.create_app())

    resp = app_client.post(
        "/api/agents/home/codespaces",
        json={"repo": "owner/name", "alias": "home-name-default", "image": "img"},
    )

    assert resp.status_code == 200


def test_create_without_github_token_logs_actionable_error(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN")

    with caplog.at_level("WARNING", logger="codespace.client.web"):
        resp = app_client.post(
            "/api/agents/home/codespaces",
            json={"repo": "owner/name", "alias": "home-name-default", "image": "img"},
        )

    assert resp.status_code == 400
    assert resp.json() == {
        "error": "GitHub token is not available in the Web GUI process; set GITHUB_TOKEN "
        "before starting `python -m codespace.client web`, or configure github.token_env "
        "in config.yaml."
    }
    assert "Rejecting create codespace request for agent home" in caplog.text
    assert "GITHUB_TOKEN" in caplog.text


def test_delete_without_github_token_still_deletes_remote(
    app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codespace.client import service

    monkeypatch.delenv("GITHUB_TOKEN")

    def _delete(
        self: service.CodespaceService,
        agent_id: str,
        codespace_id: str,
        *,
        token: str | None,
        alias: str | None = None,
        repo: str | None = None,
        purge: bool = False,
    ) -> service.DeleteCodespaceResult:
        assert agent_id == "home"
        assert codespace_id == "abc123"
        assert token is None
        assert repo == "owner/name"
        assert purge is True
        assert alias is None
        return service.DeleteCodespaceResult(
            ok=True,
            workspace_removed=True,
            warning="GitHub token is not available; skipped deploy key revocation",
        )

    monkeypatch.setattr(service.CodespaceService, "delete_codespace", _delete)

    resp = app_client.delete("/api/agents/home/codespaces/abc123?repo=owner/name&purge=true")

    assert resp.status_code == 200
    assert resp.json() == {
        "ok": True,
        "workspace_removed": True,
        "warning": "GitHub token is not available; skipped deploy key revocation",
    }
