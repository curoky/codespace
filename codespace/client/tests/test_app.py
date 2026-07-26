"""Tests for the reduced local Web API and native static assets."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from codespace.client.app import create_app
from codespace.client.config import Config
from codespace.client.models import (
    DashboardResponse,
    HostStatus,
    ProjectSummary,
)
from codespace.client.operations import OperationStore


class FakeService:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.operations = OperationStore()
        self.tokens = {"github": False, "gitlab": False}
        self.created: list[tuple[str, str]] = []
        self.deleted: list[tuple[str, str, bool]] = []
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
            projects=[
                ProjectSummary(
                    id="devspace",
                    host="home",
                    provider="github",
                    repo="curoky/devspace",
                    image=self.config.default_image,
                )
            ],
            environments=[],
            operations=self.operations.list(),
            tokens={  # type: ignore[arg-type]
                "github": self.tokens["github"],
                "gitlab": self.tokens["gitlab"],
            },
        )

    def queue_create(self, project: str, instance: str) -> str:
        if project not in self.config.projects:
            raise KeyError(f"unknown project: {project}")
        if not self.tokens["github"]:
            raise RuntimeError("github token is not set")
        return self.operations.create("home", project, instance).id

    def create(self, project: str, instance: str) -> None:
        self.created.append((project, instance))

    def delete(self, project: str, instance: str, *, purge: bool) -> None:
        if project not in self.config.projects:
            raise KeyError(f"unknown project: {project}")
        self.deleted.append((project, instance, purge))


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
    assert "react" not in script.text.lower()
    assert "radix" not in stylesheet.text.lower()


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
    assert body["projects"][0]["id"] == "devspace"
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
        "/api/projects/devspace/instances",
        json={"instance": "debug"},
    )
    assert missing.status_code == 409
    assert missing.json() == {"error": "github token is not set"}

    client.put("/api/tokens/github", json={"token": "token"})
    created = client.post(
        "/api/projects/devspace/instances",
        json={"instance": "debug"},
    )

    assert created.status_code == 202
    assert created.json() == {
        "id": "codespace-home-devspace-debug",
        "host": "home",
        "project": "devspace",
        "instance": "debug",
        "status": "queued",
        "stage": "queued",
        "error": None,
    }
    assert service.created == [("devspace", "debug")]


def test_create_rejects_unknown_fields_and_invalid_ids(
    app_client: tuple[TestClient, FakeService],
) -> None:
    client, _service = app_client

    invalid_body = client.post(
        "/api/projects/devspace/instances",
        json={"instance": "debug", "image": "override"},
    )
    invalid_path = client.request(
        "DELETE",
        "/api/projects/devspace/instances/Bad?purge=false",
    )

    assert invalid_body.status_code == 422
    assert invalid_body.json()["error"].startswith("body.image:")
    assert invalid_path.status_code == 422
    assert invalid_path.json()["error"].startswith("path.instance:")


@pytest.mark.parametrize("purge", [False, True])
def test_delete_api_passes_purge_choice(
    app_client: tuple[TestClient, FakeService],
    purge: bool,
) -> None:
    client, service = app_client

    response = client.request(
        "DELETE",
        f"/api/projects/devspace/instances/debug?purge={str(purge).lower()}",
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "workspace_removed": purge}
    assert service.deleted == [("devspace", "debug", purge)]


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
