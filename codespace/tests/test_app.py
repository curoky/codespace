"""Tests for the agent FastAPI routes with podman mocked out.

The agent no longer talks to GitHub, so only podman is stubbed. Orchestration
detail lives in test_service.py; these tests exercise the HTTP surface.
"""

import time

import pytest
from fastapi.testclient import TestClient
from podman.errors import NotFound

from codespace import shared
from codespace.agent import app as app_module
from codespace.agent import containers, credentials, keys
from codespace.agent.config import AgentConfig


@pytest.fixture
def config() -> AgentConfig:
    return AgentConfig(
        workspace_root_host="/var/lib/cs",
        podman_uri="unix:///run/podman/podman.sock",
    )


@pytest.fixture
def client(config: AgentConfig, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # The agent opens a PodmanClient as a context manager; stub it so no socket
    # is touched. Individual tests override the container ops they need.
    class _DummyClient:
        def __enter__(self) -> "_DummyClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(app_module, "PodmanClient", lambda *a, **k: _DummyClient())
    monkeypatch.setattr(containers, "ensure_workspace_dir", lambda *a: None)
    monkeypatch.setattr(containers, "wait_for_ssh_ready", lambda *a: None)
    return TestClient(app_module.create_app(config))


def _create_body() -> dict:
    return {
        "repo": "owner/name",
        "login_pubkey": "ssh-ed25519 AAAA",
        "image": "codespace/dev:latest",
    }


def _operation_result(client: TestClient, operation_id: str) -> dict:
    for _ in range(20):
        resp = client.get(f"/operations/{operation_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in {"succeeded", "failed"}:
            return body
        time.sleep(0.01)
    return body


def test_create_success_returns_public_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        keys,
        "generate_deploy_keypair",
        lambda: keys.DeployKeypair(private_openssh="PRIV", public_openssh="ssh-ed25519 PUB"),
    )
    monkeypatch.setattr(
        containers,
        "create_container",
        lambda *a, **k: containers.ContainerInfo(container_id="cid", port=49207),
    )
    monkeypatch.setattr(containers, "find_container_by_instance", lambda *a: None)
    monkeypatch.setattr(containers, "pull_image", lambda *a: None)
    monkeypatch.setattr(credentials, "inject_credentials", lambda *a, **k: None)

    resp = client.post("/codespaces", json=_create_body())
    assert resp.status_code == 202
    operation = resp.json()
    assert operation["id"]
    body = _operation_result(client, operation["id"])["codespace"]
    assert body["id"]
    assert body["port"] == 49207
    assert body["deploy_keys"] == [
        {
            "repo": "owner/name",
            "provider": "github",
            "public_openssh": "ssh-ed25519 PUB",
            "read_only": False,
        }
    ]


def test_create_rejects_invalid_repo(client: TestClient) -> None:
    resp = client.post(
        "/codespaces",
        json={"repo": "invalid", "login_pubkey": "ssh-ed25519 AAAA", "image": "img"},
    )
    assert resp.status_code == 422  # pydantic validation at the boundary


def test_get_operation_returns_404_for_missing_id(client: TestClient) -> None:
    resp = client.get("/operations/missing")
    assert resp.status_code == 404
    assert resp.json() == {"error": "operation not found"}


def test_list_codespaces(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = shared.Codespace(
        id="abc",
        port=49207,
        user="dev",
        container_id="cid",
        repo="owner/name",
        template="default",
        instance="default",
        workspace_dir="codespace-owner-name-default-deadbeef",
    )
    monkeypatch.setattr(containers, "list_containers", lambda client: ["c"])
    monkeypatch.setattr(containers, "to_codespace", lambda c: sample)

    resp = client.get("/codespaces")
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "abc"


def test_delete_missing_is_idempotent(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(containers, "get_container", lambda client, cs_id: None)
    resp = client.request("DELETE", "/codespaces/nope")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "workspace_removed": False}


def test_delete_existing_removes_container(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    removed: list[object] = []
    monkeypatch.setattr(containers, "get_container", lambda client, cs_id: object())
    monkeypatch.setattr(
        containers,
        "read_label",
        lambda container, key, default="": {
            shared.LABEL_REPO: "owner/name",
            shared.LABEL_TEMPLATE: "default",
            shared.LABEL_INSTANCE: "default",
        }.get(key, default),
    )
    monkeypatch.setattr(containers, "remove_container", lambda c: removed.append(c))
    purged: list[str] = []
    monkeypatch.setattr(containers, "purge_workspace", lambda client, d: purged.append(d))

    resp = client.request("DELETE", "/codespaces/abc123")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "workspace_removed": False}
    assert len(removed) == 1  # container removed
    assert purged == []  # no purge without ?purge=true


def test_delete_with_purge_removes_workspace(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(containers, "get_container", lambda client, cs_id: object())
    monkeypatch.setattr(
        containers,
        "read_label",
        lambda container, key, default="": {
            shared.LABEL_REPO: "owner/name",
            shared.LABEL_TEMPLATE: "default",
            shared.LABEL_INSTANCE: "default",
        }.get(key, default),
    )
    monkeypatch.setattr(containers, "stop_container", lambda c: None)
    monkeypatch.setattr(containers, "remove_container", lambda c: None)
    purged: list[str] = []
    monkeypatch.setattr(containers, "purge_workspace", lambda client, d: purged.append(d))

    resp = client.request("DELETE", "/codespaces/abc123?purge=true")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "workspace_removed": True}
    # purge target is <workspace_root>/<workspace_dir>
    assert purged == [
        "/var/lib/cs/" + shared.workspace_dir_name("owner/name", "default", "default")
    ]


def test_delete_with_purge_purges_before_removing_container(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    monkeypatch.setattr(containers, "get_container", lambda client, cs_id: object())
    monkeypatch.setattr(
        containers,
        "read_label",
        lambda container, key, default="": {
            shared.LABEL_REPO: "owner/name",
            shared.LABEL_TEMPLATE: "default",
            shared.LABEL_INSTANCE: "default",
        }.get(key, default),
    )
    monkeypatch.setattr(containers, "stop_container", lambda c: events.append("stop"))
    monkeypatch.setattr(containers, "purge_workspace", lambda client, d: events.append("purge"))
    monkeypatch.setattr(containers, "remove_container", lambda c: events.append("remove"))

    resp = client.request("DELETE", "/codespaces/abc123?purge=true")

    assert resp.status_code == 200
    assert events == ["stop", "purge", "remove"]


def test_clone_codespace_repo(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    container = object()
    cloned: list[tuple[str, str, str]] = []
    monkeypatch.setattr(containers, "get_container", lambda client, cs_id: container)
    monkeypatch.setattr(
        containers,
        "read_label",
        lambda container, key, default="": {
            shared.LABEL_REPO: "owner/name",
            shared.LABEL_USER: "dev",
        }.get(key, default),
    )
    monkeypatch.setattr(
        credentials,
        "clone_repo",
        lambda client, *, cs_id, user, repo, provider: cloned.append((cs_id, user, repo)),
    )

    resp = client.post("/codespaces/abc123/clone")

    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    assert cloned == [("abc123", "dev", "owner/name")]


def test_clone_codespace_repo_returns_404_when_deleted_during_clone(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = object()
    result = iter([container, None])
    monkeypatch.setattr(containers, "get_container", lambda client, cs_id: next(result))
    monkeypatch.setattr(
        containers,
        "read_label",
        lambda container, key, default="": {
            shared.LABEL_REPO: "owner/name",
            shared.LABEL_USER: "dev",
        }.get(key, default),
    )

    def _clone_repo(*args: object, **kwargs: object) -> None:
        raise NotFound("no such exec session")

    monkeypatch.setattr(credentials, "clone_repo", _clone_repo)

    resp = client.post("/codespaces/abc123/clone")

    assert resp.status_code == 404
    assert resp.json() == {"error": "codespace not found"}
