"""Tests for the final local Web API and native static assets."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from codespace.config import Config
from codespace.control import HostInventory
from codespace.errors import ResourceConflict, ResourceNotFound
from codespace.operations import Operation, OperationStore
from codespace.web.app import create_app, router
from codespace.web.models import DashboardWorkspace
from codespace.workspaces.models import EmptySource, RepoGitState, Workspace, workspace_identity


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
        self.deleted: list[tuple[str, str, str, bool]] = []
        self.inspected: list[tuple[str, str, str]] = []
        self.logs_read: list[tuple[str, str, str]] = []
        self.tunnels_opened: list[tuple[str, str, str, int]] = []
        self.state = RepoGitState(unpushed=False, uncommitted=False, detail=[])

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

    def inspect_deletion(self, project: str, host: str, workspace: str) -> RepoGitState:
        self.inspected.append((project, host, workspace))
        return self.state

    def delete(
        self,
        project: str,
        host: str,
        workspace: str,
        *,
        purge: bool,
    ) -> None:
        self.deleted.append((project, host, workspace, purge))

    def logs(
        self,
        project: str,
        host: str,
        workspace: str,
    ) -> str:
        if workspace == "missing":
            raise ResourceNotFound("workspace not found")
        self.logs_read.append((project, host, workspace))
        return "log line\n"

    def open_tunnel(self, project: str, host: str, workspace: str, port: int) -> int:
        if workspace == "stopped":
            raise ResourceConflict("Tunnel requires a running Workspace")
        self.tunnels_opened.append((project, host, workspace, port))
        return 49123


class FakeServiceManager:
    def __init__(self) -> None:
        self.operations = OperationStore()
        self.applied: list[tuple[str, str]] = []
        self.logs_read: list[tuple[str, str]] = []

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

    def logs(self, service: str, host: str) -> str:
        self.logs_read.append((service, host))
        return "service log\n"


class FakeControl:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.tokens = FakeTokens()
        self.workspaces = FakeWorkspaceManager()
        self.services = FakeServiceManager()
        self.inventories = {host: HostInventory(host, [], []) for host in config.hosts}
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def inventory(self) -> dict[str, HostInventory]:
        return self.inventories


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
    assert "workspace.encrypted" in script
    assert "Encrypted Workspace" in script
    assert "logs-source" not in index
    assert "renderLogSources" not in script
    assert "?source=" not in script
    assert ".workspace-actions .ssh-command" in stylesheet
    assert ".workspace-encryption-icon" in stylesheet


def test_dashboard_workspace_exposes_container_encryption(
    app_client: tuple[TestClient, FakeControl], monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(
        project="codespace",
        workspace="debug",
        host="home",
        source=EmptySource(type="empty"),
        image="workspace:latest",
        platform="native",
        open_path="/workspace",
        encrypted=True,
        container_id="container-id",
        status="running",
    )

    dashboard_workspace = DashboardWorkspace.model_validate(workspace, from_attributes=True)

    assert dashboard_workspace.encrypted is True
    serialized = dashboard_workspace.model_dump()
    assert serialized["source"] == {"type": "empty"}
    assert serialized["ssh_command"] == "ssh codespace-workspace-24831_home_codespace_debug"
    assert "ssh-remote+codespace-workspace-24831_home_codespace_debug" in serialized["trae_url"]
    assert "/workspace?" in serialized["trae_url"]
    assert serialized["trae_cn_url"].startswith("trae-cn://")
    assert "container_id" not in serialized
    assert "alias" not in serialized
    client, control = app_client
    control.inventories["home"] = HostInventory("home", [workspace], [])

    response = client.get("/api/dashboard")

    assert response.status_code == 200
    assert response.json()["workspaces"] == [serialized]
    project = response.json()["projects"][0]
    assert project["source"] == {"type": "github", "repository": "curoky/codespace"}
    assert not {"repository", "git_url", "checkout_path"} & project.keys()


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
        "/api/projects/codespace/hosts/home/workspaces/debug?purge=true",
    )
    logs = client.get("/api/projects/codespace/hosts/home/workspaces/debug/logs")

    assert created.status_code == 202
    assert created.json()["id"] == "codespace-workspace_home_codespace_debug"
    assert control.workspaces.created == [("codespace", "home", "debug")]
    assert deleted.json()["data_removed"] is True
    assert control.workspaces.logs_read == [("codespace", "home", "debug")]
    assert logs.json() == {"logs": "log line\n"}


def test_tunnel_route_redirects_and_reports_failure(
    app_client: tuple[TestClient, FakeControl],
) -> None:
    client, control = app_client
    path = "/api/projects/codespace/hosts/home/workspaces"

    opened = client.post(f"{path}/debug/tunnels/8005", follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == "http://127.0.0.1:49123/"
    assert control.workspaces.tunnels_opened == [("codespace", "home", "debug", 8005)]

    stopped = client.post(f"{path}/stopped/tunnels/8005")
    assert stopped.status_code == 409
    assert stopped.json() == {"error": "Tunnel requires a running Workspace"}
    assert client.get(f"{path}/debug/tunnels/8005").status_code == 405
    assert client.post(f"{path}/bad_name/tunnels/8005").status_code == 422
    for port in ("0", "65536", "invalid"):
        assert client.post(f"{path}/debug/tunnels/{port}").status_code == 422


def test_service_routes_apply_log_and_remove(
    app_client: tuple[TestClient, FakeControl],
) -> None:
    client, control = app_client

    applied = client.post("/api/services/support/hosts/home/apply")
    logs = client.get("/api/services/support/hosts/home/logs")
    removed = client.request("DELETE", "/api/services/support/hosts/home?purge=true")

    assert applied.status_code == 202
    assert control.services.applied == [("support", "home")]
    assert control.services.logs_read == [("support", "home")]
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
        ("POST", "/api/projects/{project}/hosts/{host}/workspaces/{workspace}/tunnels/{port}"),
        ("GET", "/api/projects/{project}/hosts/{host}/workspaces/{workspace}/deletion-check"),
        ("DELETE", "/api/projects/{project}/hosts/{host}/workspaces/{workspace}"),
        ("DELETE", "/api/projects/{project}/hosts/{host}/operations/{workspace}"),
        ("POST", "/api/services/{service}/hosts/{host}/apply"),
        ("GET", "/api/services/{service}/hosts/{host}/logs"),
        ("DELETE", "/api/services/{service}/hosts/{host}"),
        ("DELETE", "/api/services/{service}/hosts/{host}/operation"),
    }


@pytest.mark.parametrize("purge", [False, True])
def test_deletion_check_is_read_only_and_delete_only_executes(
    app_client: tuple[TestClient, FakeControl], purge: bool
) -> None:
    client, control = app_client
    path = "/api/projects/codespace/hosts/home/workspaces/debug"
    control.workspaces.state = RepoGitState(unpushed=True, uncommitted=False, detail=["commit"])

    checked = client.get(f"{path}/deletion-check")
    assert checked.json() == control.workspaces.state.model_dump()
    assert control.workspaces.deleted == []
    assert control.workspaces.inspected == [("codespace", "home", "debug")]
    assert client.delete(f"{path}?force=true").status_code == 422
    assert control.workspaces.deleted == []

    deleted = client.delete(path, params={"purge": str(purge).lower()})
    assert deleted.json() == {"deleted": True, "data_removed": purge}
    assert control.workspaces.deleted == [("codespace", "home", "debug", purge)]
    assert len(control.workspaces.inspected) == 1


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (ResourceNotFound("not found"), 404),
        (ResourceConflict("busy"), 409),
        (KeyError("codespace.image"), 500),
        (RuntimeError("runtime failed"), 500),
    ],
)
def test_only_explicit_resource_errors_map_to_client_status(
    app_client: tuple[TestClient, FakeControl],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status: int,
) -> None:
    original, control = app_client

    def fail(*_args: object) -> None:
        raise error

    monkeypatch.setattr(control.workspaces, "inspect_deletion", fail)
    client = TestClient(original.app, raise_server_exceptions=False)
    response = client.get("/api/projects/codespace/hosts/home/workspaces/debug/deletion-check")
    assert response.status_code == status
    assert str(error) in response.json()["error"]
