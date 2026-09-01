"""Tests for the reduced local Web API and native static assets."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from controller.app import create_app
from controller.config import Config
from controller.models import (
    DashboardResponse,
    HostStatus,
    Operation,
    RepoGitState,
    WorkspaceSummary,
    WorkspaceSummaryHost,
    environment_id,
)
from controller.operations import OperationStore


class FakeService:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.operations = OperationStore[Operation]()
        self.tokens = {"github": False, "gitlab": False}
        self.created: list[tuple[str, str, str]] = []
        self.deleted: list[tuple[str, str, str, bool, bool]] = []
        self.state: RepoGitState = RepoGitState()
        self.logs_text = "2026-08-19T00:00:00Z boot\n"
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def token_status(self) -> dict[str, bool]:
        return dict(self.tokens)

    def set_token(self, provider: str, token: str) -> None:
        assert token
        self.tokens[provider] = True

    def dashboard(self) -> DashboardResponse:
        return DashboardResponse(
            hosts=[HostStatus(id="home", status="online")],
            workspaces=[
                WorkspaceSummary(
                    id="devspace",
                    hosts=[WorkspaceSummaryHost(name="home", platform=None)],
                    type="repo",
                    provider="github",
                    repo="curoky/devspace",
                    image=self.config.workspaces.defaults.image,
                    open_path="/opt/devspace",
                )
            ],
            environments=[],
            deployments=[],
            operations=self.operations.list(),
            tokens={  # type: ignore[arg-type]
                "github": self.tokens["github"],
                "gitlab": self.tokens["gitlab"],
            },
        )

    def queue_create(self, workspace: str, host: str, instance: str) -> Operation:
        if workspace not in self.config.workspaces.items:
            raise KeyError(f"unknown workspace: {workspace}")
        if not self.tokens["github"]:
            raise RuntimeError("github token is not set")
        return self.operations.create(
            Operation(
                id=environment_id(host, workspace, instance),
                host=host,
                workspace=workspace,
                instance=instance,
                status="queued",
                stage="queued",
            )
        )

    def create(self, workspace: str, host: str, instance: str) -> None:
        self.created.append((workspace, host, instance))

    def dismiss_failed_operation(self, workspace: str, host: str, instance: str) -> bool:
        return self.operations.dismiss_failed(host, environment_id(host, workspace, instance))

    def delete(
        self, workspace: str, host: str, instance: str, *, purge: bool, force: bool = False
    ) -> RepoGitState:
        if workspace not in self.config.workspaces.items:
            raise KeyError(f"unknown workspace: {workspace}")
        if not force:
            return self.state
        self.deleted.append((workspace, host, instance, purge, force))
        return RepoGitState()

    def logs(self, workspace: str, host: str, instance: str) -> str:
        if workspace not in self.config.workspaces.items:
            raise KeyError(f"unknown workspace: {workspace}")
        if instance == "missing":
            raise RuntimeError(f"environment {instance!r} not found")
        return self.logs_text


@pytest.fixture
def app_client(config: Config) -> tuple[TestClient, FakeService]:
    service = FakeService(config)
    return TestClient(create_app(config, service=service)), service  # type: ignore[arg-type]


def test_static_assets_are_native_sources(app_client: tuple[TestClient, FakeService]) -> None:
    client, _service = app_client

    index = client.get("/")
    script = client.get("/static/app.js")
    stylesheet = client.get("/static/app.css")

    assert index.status_code == 200
    assert "/static/app.js" in index.text
    assert 'class="app-header"' in index.text
    assert 'class="brand-mark"' not in index.text
    assert 'aria-label="Close"' in index.text
    assert "react" not in script.text.lower()
    assert "radix" not in stylesheet.text.lower()
    assert "workspace-source" in script.text
    assert "title.append(name, sourceLine)" in script.text
    assert "header.append(title, headerActions)" in script.text
    assert "environment.ssh_command" in script.text
    assert "SSH port" not in script.text
    assert script.text.index('link("Trae CN"') < script.text.index("actions.append(sshButton)")
    assert "navigator.clipboard.writeText(command)" in script.text
    assert 'status: environment.status || "unknown"' in script.text
    assert '(type === "repo" || type === "git") && status !== "running"' in script.text
    assert 'button.textContent = "Copied"' in script.text
    assert '"dismiss-operation", dismissTarget)' in script.text
    assert 'aria-label", "Dismiss failed operation"' in script.text
    assert ".environment-actions .ssh-command" in stylesheet.text
    assert ".environment-actions .ssh-command.copied" in stylesheet.text
    assert "button.operation-dismiss" in stylesheet.text
    assert "prefers-reduced-motion" in stylesheet.text


def test_dashboard_returns_all_state_and_token_presence(
    app_client: tuple[TestClient, FakeService],
) -> None:
    client, _service = app_client

    body = client.get("/api/dashboard").json()

    assert body["hosts"] == [
        {
            "id": "home",
            "status": "online",
            "environment_count": 0,
            "error": None,
            "inventory_errors": [],
        }
    ]
    assert body["workspaces"][0]["id"] == "devspace"
    assert body["tokens"] == {"github": False, "gitlab": False}
    assert body["operations"] == []


def test_token_api_never_returns_token_value(
    app_client: tuple[TestClient, FakeService],
) -> None:
    client, _service = app_client

    response = client.put("/api/tokens/github", json={"token": "secret-token"})

    assert response.status_code == 200
    assert response.json() == {"github": True, "gitlab": False}
    assert "secret-token" not in response.text


def test_create_requires_token_and_returns_local_operation(
    app_client: tuple[TestClient, FakeService],
) -> None:
    client, service = app_client

    missing = client.post(
        "/api/workspaces/devspace/instances",
        json={"host": "home", "instance": "debug"},
    )
    assert missing.status_code == 409
    assert missing.json() == {"error": "github token is not set"}

    client.put("/api/tokens/github", json={"token": "token"})
    created = client.post(
        "/api/workspaces/devspace/instances",
        json={"host": "home", "instance": "debug"},
    )

    assert created.status_code == 202
    assert created.json() == {
        "id": "codespace-home-devspace-debug",
        "host": "home",
        "workspace": "devspace",
        "instance": "debug",
        "status": "queued",
        "stage": "queued",
        "error": None,
    }
    assert service.created == [("devspace", "home", "debug")]


def test_create_rejects_unknown_fields_and_invalid_ids(
    app_client: tuple[TestClient, FakeService],
) -> None:
    client, _service = app_client

    invalid_body = client.post(
        "/api/workspaces/devspace/instances",
        json={"host": "home", "instance": "debug", "image": "override"},
    )
    invalid_path = client.request(
        "DELETE",
        "/api/workspaces/devspace/hosts/home/instances/Bad?purge=false",
    )

    assert invalid_body.status_code == 422
    assert invalid_body.json()["error"].startswith("body.image:")
    assert invalid_path.status_code == 422
    assert invalid_path.json()["error"].startswith("path.instance:")


def test_dismiss_operation_rejects_active_work_and_removes_failure(
    app_client: tuple[TestClient, FakeService],
) -> None:
    client, service = app_client
    operation = service.operations.create(
        Operation(
            id=environment_id("home", "devspace", "debug"),
            host="home",
            workspace="devspace",
            instance="debug",
            status="queued",
            stage="queued",
        )
    )
    path = "/api/workspaces/devspace/hosts/home/operations/debug"

    active = client.delete(path)

    assert active.status_code == 409
    assert active.json()["error"].endswith("is still queued")

    service.operations.update("home", operation.id, status="failed")
    dismissed = client.delete(path)

    assert dismissed.status_code == 200
    assert dismissed.json() == {"dismissed": True}
    assert service.operations.list() == []
    assert client.delete(path).json() == {"dismissed": False}


@pytest.mark.parametrize("purge", [False, True])
def test_delete_api_passes_purge_choice(
    app_client: tuple[TestClient, FakeService],
    purge: bool,
) -> None:
    client, service = app_client

    response = client.request(
        "DELETE",
        f"/api/workspaces/devspace/hosts/home/instances/debug?purge={str(purge).lower()}&force=true",
    )

    assert response.status_code == 200
    assert response.json() == {
        "deleted": True,
        "workspace_removed": purge,
        "state": {"unpushed": False, "uncommitted": False, "detail": []},
    }
    assert service.deleted == [("devspace", "home", "debug", purge, True)]


def test_delete_without_force_returns_git_state_and_skips_delete(
    app_client: tuple[TestClient, FakeService],
) -> None:
    client, service = app_client
    service.state = RepoGitState(unpushed=True, uncommitted=True, detail=["abc feat", " M x"])

    response = client.request("DELETE", "/api/workspaces/devspace/hosts/home/instances/debug")

    assert response.status_code == 200
    body = response.json()
    assert body["deleted"] is False
    assert body["workspace_removed"] is False
    assert body["state"] == {
        "unpushed": True,
        "uncommitted": True,
        "detail": ["abc feat", " M x"],
    }
    assert service.deleted == []

    forced = client.request(
        "DELETE",
        "/api/workspaces/devspace/hosts/home/instances/debug?force=true",
    )

    assert forced.status_code == 200
    assert service.deleted == [("devspace", "home", "debug", False, True)]


def test_only_documented_api_routes_exist(
    app_client: tuple[TestClient, FakeService],
) -> None:
    client, _service = app_client

    for path in (
        "/api/config",
        "/api/provider-tokens",
        "/api/operations/anything",
        "/api/operations/stream",
        "/codespaces",
    ):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json() == {"error": "Not Found"}


def test_logs_returns_container_output(
    app_client: tuple[TestClient, FakeService],
) -> None:
    client, service = app_client
    service.logs_text = "2026-08-19T00:00:00Z hello\n"

    response = client.get("/api/workspaces/devspace/hosts/home/instances/debug/logs")

    assert response.status_code == 200
    assert response.json() == {"logs": "2026-08-19T00:00:00Z hello\n"}


def test_logs_missing_environment_returns_conflict(
    app_client: tuple[TestClient, FakeService],
) -> None:
    client, _service = app_client

    response = client.get("/api/workspaces/devspace/hosts/home/instances/missing/logs")

    assert response.status_code == 409
    assert response.json()["error"].endswith("not found")


def test_logs_ui_wires_button_and_dialog(
    app_client: tuple[TestClient, FakeService],
) -> None:
    client, _service = app_client

    index = client.get("/").text
    script = client.get("/static/app.js").text
    stylesheet = client.get("/static/app.css").text

    assert 'id="logs-dialog"' in index
    assert 'class="logs-output"' in index
    assert 'actionButton("Logs", "logs", target)' in script
    assert 'if (action === "logs") openLogsDialog(workspace, host, instance)' in script
    assert "/instances/${encodeURIComponent(instance)}/logs" in script
    assert ".logs-output" in stylesheet
