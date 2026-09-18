"""Tests for the final local Web API and native static assets."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from codespace.config import Config
from codespace.control import HostInventory
from codespace.operations import Operation, OperationStore
from codespace.resources import Resource, ResourceConflict, ResourceNotFound
from codespace.web.app import create_app, router
from codespace.workspaces import EmptySource, RepoGitState, Workspace


class FakeControl:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.tokens = {"github": False, "gitlab": False}
        self.inventories = {host: HostInventory(host, [], []) for host in config.hosts}
        self.closed = False
        self.operations = OperationStore()
        self.deployed: list[Resource] = []
        self.deleted: list[tuple[Resource, bool]] = []
        self.inspected: list[Resource] = []
        self.logs_read: list[Resource] = []
        self.tunnels_opened: list[tuple[Resource, int]] = []
        self.state = RepoGitState(unpushed=False, uncommitted=False, detail=[])

    def set_token(self, provider: str, token: str) -> None:
        assert token
        self.tokens[provider] = True

    def token_status(self) -> dict[str, bool]:
        return dict(self.tokens)

    def close(self) -> None:
        self.closed = True

    def inventory(self) -> dict[str, HostInventory]:
        return self.inventories

    def queue(self, resource: Resource) -> Operation:
        return self.operations.create(
            Operation(
                id=resource.id,
                kind=resource.kind,
                host=resource.host,
                resource=resource.name,
                project=resource.project,
                status="queued",
                stage="queued",
            )
        )

    def deploy(self, resource: Resource) -> None:
        self.deployed.append(resource)

    def dismiss_failed(self, resource: Resource) -> bool:
        return self.operations.dismiss_failed(resource.host, resource.id)

    def inspect_deletion(self, resource: Resource) -> RepoGitState:
        self.inspected.append(resource)
        return self.state

    def remove(self, resource: Resource, *, purge: bool) -> bool:
        self.deleted.append((resource, purge))
        return True

    def logs(self, resource: Resource) -> str:
        if resource.name == "missing":
            raise ResourceNotFound("workspace not found")
        self.logs_read.append(resource)
        return "log line\n" if resource.project is not None else "service log\n"

    def open_tunnel(self, resource: Resource, port: int) -> int:
        if resource.name == "stopped":
            raise ResourceConflict("Tunnel requires a running Workspace")
        self.tunnels_opened.append((resource, port))
        return 49123 if resource.project is not None else port


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
    assert "/tunnels/${port}" in script
    assert 'portLink.target = "_blank"' in script
    assert "openWorkspaceTunnel" not in script
    assert 'form.target = "_blank"' not in script
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

    client, control = app_client
    control.inventories["home"] = HostInventory("home", [workspace], [])
    response = client.get("/api/dashboard")
    assert response.status_code == 200
    serialized = response.json()["workspaces"][0]

    assert serialized["encrypted"] is True
    assert serialized["source"] == {"type": "empty"}
    assert serialized["ssh_command"] == "ssh space-codespace-debug-home"
    assert "ssh-remote+space-codespace-debug-home" in serialized["trae_url"]
    assert "/workspace?" in serialized["trae_url"]
    assert serialized["trae_cn_url"].startswith("trae-cn://")
    assert serialized["vscode_url"].startswith("vscode://")
    assert "ssh-remote+space-codespace-debug-home" in serialized["vscode_url"]
    assert "container_id" not in serialized
    assert "alias" not in serialized
    project = response.json()["projects"][0]
    assert project["source"] == {
        "type": "github",
        "repository": "curoky/codespace",
        "args": [],
    }
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
    assert created.json()["id"] == "space:codespace/debug@home"
    assert control.deployed == [Resource("home", "debug", "codespace")]
    assert deleted.json()["data_removed"] is True
    assert control.logs_read == [Resource("home", "debug", "codespace")]
    assert logs.json() == {"logs": "log line\n"}


def test_tunnel_route_redirects_and_reports_failure(
    app_client: tuple[TestClient, FakeControl],
) -> None:
    client, control = app_client
    path = "/api/projects/codespace/hosts/home/workspaces"

    opened = client.get(f"{path}/debug/tunnels/8005", follow_redirects=False)
    assert opened.status_code == 303
    assert opened.headers["location"] == "http://127.0.0.1:49123/"
    assert control.tunnels_opened == [(Resource("home", "debug", "codespace"), 8005)]

    stopped = client.get(f"{path}/stopped/tunnels/8005")
    assert stopped.status_code == 409
    assert stopped.json() == {"error": "Tunnel requires a running Workspace"}
    assert client.post(f"{path}/debug/tunnels/8005").status_code == 405
    assert client.get(f"{path}/bad_name/tunnels/8005").status_code == 422
    for port in ("0", "65536", "invalid"):
        assert client.get(f"{path}/debug/tunnels/{port}").status_code == 422


def test_service_routes_apply_log_and_remove(
    app_client: tuple[TestClient, FakeControl],
) -> None:
    client, control = app_client

    applied = client.post("/api/services/support/hosts/home/apply")
    logs = client.get("/api/services/support/hosts/home/logs")
    removed = client.request("DELETE", "/api/services/support/hosts/home?purge=true")

    assert applied.status_code == 202
    assert control.deployed == [Resource("home", "support")]
    assert control.logs_read == [Resource("home", "support")]
    assert logs.json() == {"logs": "service log\n"}
    assert removed.json() == {"removed": True, "data_removed": True}


def test_service_tunnel_route_redirects_to_local_forward(
    app_client: tuple[TestClient, FakeControl],
) -> None:
    client, control = app_client

    opened = client.get(
        "/api/services/support/hosts/home/tunnels/3210",
        follow_redirects=False,
    )

    assert opened.status_code == 303
    assert opened.headers["location"] == "http://127.0.0.1:3210/"
    assert control.tunnels_opened == [(Resource("home", "support"), 3210)]


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
        ("GET", "/api/projects/{project}/hosts/{host}/workspaces/{workspace}/tunnels/{port}"),
        ("GET", "/api/projects/{project}/hosts/{host}/workspaces/{workspace}/deletion-check"),
        ("DELETE", "/api/projects/{project}/hosts/{host}/workspaces/{workspace}"),
        ("DELETE", "/api/projects/{project}/hosts/{host}/operations/{workspace}"),
        ("POST", "/api/services/{service}/hosts/{host}/apply"),
        ("GET", "/api/services/{service}/hosts/{host}/logs"),
        ("GET", "/api/services/{service}/hosts/{host}/tunnels/{port}"),
        ("DELETE", "/api/services/{service}/hosts/{host}"),
        ("DELETE", "/api/services/{service}/hosts/{host}/operation"),
    }


@pytest.mark.parametrize("purge", [False, True])
def test_deletion_check_is_read_only_and_delete_only_executes(
    app_client: tuple[TestClient, FakeControl], purge: bool
) -> None:
    client, control = app_client
    path = "/api/projects/codespace/hosts/home/workspaces/debug"
    control.state = RepoGitState(unpushed=True, uncommitted=False, detail=["commit"])

    checked = client.get(f"{path}/deletion-check")
    assert checked.json() == control.state.model_dump()
    assert control.deleted == []
    assert control.inspected == [Resource("home", "debug", "codespace")]
    assert client.delete(f"{path}?force=true").status_code == 422
    assert control.deleted == []

    deleted = client.delete(path, params={"purge": str(purge).lower()})
    assert deleted.json() == {"deleted": True, "data_removed": purge}
    assert control.deleted == [(Resource("home", "debug", "codespace"), purge)]
    assert len(control.inspected) == 1


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

    monkeypatch.setattr(control, "inspect_deletion", fail)
    client = TestClient(original.app, raise_server_exceptions=False)
    response = client.get("/api/projects/codespace/hosts/home/workspaces/debug/deletion-check")
    assert response.status_code == status
    assert str(error) in response.json()["error"]
