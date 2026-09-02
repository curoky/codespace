"""Tests for the final local Web API and native static assets."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from codespace.config import Config
from codespace.operations import Operation, OperationStore
from codespace.web.app import create_app, router
from codespace.web.models import DashboardResponse, HostStatus, ProjectHostSummary, ProjectSummary
from codespace.workspaces.models import RepoGitState, workspace_identity


class FakeTokens:
    def __init__(self) -> None:
        self.values = {"github": False, "gitlab": False}

    def set(self, provider: str, token: str) -> None:
        assert token
        self.values[provider] = True

    def status(self) -> dict[str, bool]:
        return dict(self.values)


class FakeWorkspaceManager:
    def __init__(self) -> None:
        self.operations = OperationStore()
        self.created: list[tuple[str, str, str]] = []
        self.deleted: list[tuple[str, str, str, bool, bool]] = []
        self.state = RepoGitState()

    def queue_create(self, project: str, host: str, workspace: str) -> Operation:
        return self.operations.create(
            Operation(
                id=workspace_identity(host, project, workspace),
                kind="workspace",
                host=host,
                resource=workspace,
                project=project,
                status="queued",
                stage="queued",
            )
        )

    def create(self, project: str, host: str, workspace: str) -> None:
        self.created.append((project, host, workspace))

    def dismiss_failed(self, project: str, host: str, workspace: str) -> bool:
        return self.operations.dismiss_failed(host, workspace_identity(host, project, workspace))

    def delete(
        self,
        project: str,
        host: str,
        workspace: str,
        *,
        purge: bool,
        force: bool,
    ) -> RepoGitState:
        if force:
            self.deleted.append((project, host, workspace, purge, force))
        return self.state

    def logs(self, _project: str, _host: str, workspace: str) -> str:
        if workspace == "missing":
            raise RuntimeError("workspace not found")
        return "log line\n"


class FakeServiceManager:
    def __init__(self) -> None:
        self.operations = OperationStore()
        self.applied: list[tuple[str, str]] = []

    def queue_apply(self, service: str, host: str) -> Operation:
        return self.operations.create(
            Operation(
                id=f"codespace-service-{service}",
                kind="service",
                host=host,
                resource=service,
                status="queued",
                stage="queued",
            )
        )

    def apply(self, service: str, host: str) -> None:
        self.applied.append((service, host))

    def dismiss_failed(self, service: str, host: str) -> bool:
        return self.operations.dismiss_failed(host, f"codespace-service-{service}")

    def remove(self, _service: str, _host: str, *, purge: bool) -> bool:
        return True

    def logs(self, _service: str, _host: str) -> str:
        return "service log\n"


class FakeControl:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.tokens = FakeTokens()
        self.workspaces = FakeWorkspaceManager()
        self.services = FakeServiceManager()
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def dashboard(self) -> DashboardResponse:
        return DashboardResponse(
            hosts=[HostStatus(id="home", status="online")],
            projects=[
                ProjectSummary(
                    id="codespace",
                    hosts=[
                        ProjectHostSummary(
                            name="home",
                            platform="linux/arm64",
                            image=self.config.project_defaults.image,
                        )
                    ],
                    source="github",
                    repository="curoky/codespace",
                    checkout_path="/workspace/codespace",
                    open_path="/workspace/codespace",
                )
            ],
            workspaces=[],
            services=[],
            operations=[
                *self.workspaces.operations.list(),
                *self.services.operations.list(),
            ],
            tokens=self.tokens.status(),  # type: ignore[arg-type]
        )


@pytest.fixture
def app_client(config: Config) -> tuple[TestClient, FakeControl]:
    control = FakeControl(config)
    client = TestClient(create_app(config, control=control))  # type: ignore[arg-type]
    return client, control


def test_static_ui_uses_final_terminology(app_client: tuple[TestClient, FakeControl]) -> None:
    client, _control = app_client

    index = client.get("/").text
    script = client.get("/static/app.js").text
    stylesheet = client.get("/static/app.css").text

    assert ">Projects<" in index
    assert ">Services<" in index
    assert 'id="workspace-dialog"' in index
    assert "renderProjects" in script
    assert "renderServices" in script
    assert "/api/projects/" in script
    assert "/api/services/" in script
    assert ".workspace-actions .ssh-command" in stylesheet


def test_dashboard_and_token_endpoint_never_return_token(
    app_client: tuple[TestClient, FakeControl],
) -> None:
    client, _control = app_client

    assert client.get("/api/dashboard").json()["projects"][0]["id"] == "codespace"
    response = client.put(
        "/api/providers/github/token",
        json={"token": "secret-token"},
    )

    assert response.json() == {"github": True, "gitlab": False}
    assert "secret-token" not in response.text


def test_workspace_routes_use_project_and_workspace_identity(
    app_client: tuple[TestClient, FakeControl],
) -> None:
    client, control = app_client

    created = client.post(
        "/api/projects/codespace/workspaces",
        json={"host": "home", "workspace": "debug"},
    )
    deleted = client.request(
        "DELETE",
        "/api/projects/codespace/hosts/home/workspaces/debug?purge=true&force=true",
    )
    logs = client.get("/api/projects/codespace/hosts/home/workspaces/debug/logs")

    assert created.status_code == 202
    assert created.json()["id"] == "codespace-workspace-home-codespace-debug"
    assert control.workspaces.created == [("codespace", "home", "debug")]
    assert deleted.json()["data_removed"] is True
    assert logs.json() == {"logs": "log line\n"}


def test_service_routes_apply_log_and_remove(
    app_client: tuple[TestClient, FakeControl],
) -> None:
    client, control = app_client

    applied = client.post("/api/services/support/hosts/home/apply")
    logs = client.get("/api/services/support/hosts/home/logs")
    removed = client.request("DELETE", "/api/services/support/hosts/home?purge=true")

    assert applied.status_code == 202
    assert control.services.applied == [("support", "home")]
    assert logs.json() == {"logs": "service log\n"}
    assert removed.json() == {"removed": True, "data_removed": True}


def test_only_final_api_routes_exist(app_client: tuple[TestClient, FakeControl]) -> None:
    _client, _control = app_client
    routes = {
        (method, route.path) for route in router.routes for method in (route.methods or set())
    }

    assert routes == {
        ("GET", "/api/dashboard"),
        ("PUT", "/api/providers/{provider}/token"),
        ("POST", "/api/projects/{project}/workspaces"),
        ("GET", "/api/projects/{project}/hosts/{host}/workspaces/{workspace}/logs"),
        ("DELETE", "/api/projects/{project}/hosts/{host}/workspaces/{workspace}"),
        ("DELETE", "/api/projects/{project}/hosts/{host}/operations/{workspace}"),
        ("POST", "/api/services/{service}/hosts/{host}/apply"),
        ("GET", "/api/services/{service}/hosts/{host}/logs"),
        ("DELETE", "/api/services/{service}/hosts/{host}"),
        ("DELETE", "/api/services/{service}/hosts/{host}/operation"),
    }
