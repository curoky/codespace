"""Tests for the agent FastAPI routes with podman mocked out.

The agent no longer talks to GitHub, so only podman is stubbed.
"""

import pytest
from fastapi.testclient import TestClient

from codespace import shared
from codespace.agent import app as app_module
from codespace.agent import keys, podman_ops


@pytest.fixture
def config() -> app_module.AgentConfig:
    return app_module.AgentConfig(
        workspace_root_host="/var/lib/cs",
        podman_uri="unix:///run/podman/podman.sock",
    )


@pytest.fixture
def client(config: app_module.AgentConfig, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # The agent opens a PodmanClient as a context manager; stub it so no socket
    # is touched. Individual tests override the podman_ops functions they need.
    class _DummyClient:
        def __enter__(self) -> "_DummyClient":
            return self

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(app_module, "PodmanClient", lambda *a, **k: _DummyClient())
    return TestClient(app_module.create_app(config))


def _create_body() -> dict:
    return {
        "repo": "owner/name",
        "login_pubkey": "ssh-ed25519 AAAA",
        "image": "codespace/dev:latest",
    }


def test_create_success_returns_public_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        keys,
        "generate_deploy_keypair",
        lambda: keys.DeployKeypair(private_openssh="PRIV", public_openssh="ssh-ed25519 PUB"),
    )
    monkeypatch.setattr(
        podman_ops,
        "create_container",
        lambda *a, **k: podman_ops.ContainerInfo(container_id="cid", port=49207),
    )
    monkeypatch.setattr(podman_ops, "inject_credentials", lambda *a, **k: None)

    resp = client.post("/codespaces", json=_create_body())
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"]
    assert body["port"] == 49207
    assert body["deploy_public_key"] == "ssh-ed25519 PUB"


def test_create_provision_failure_rolls_back_and_returns_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        keys,
        "generate_deploy_keypair",
        lambda: keys.DeployKeypair(private_openssh="PRIV", public_openssh="PUB"),
    )

    def _fail(*a: object, **k: object) -> podman_ops.ContainerInfo:
        raise RuntimeError("podman down")

    monkeypatch.setattr(podman_ops, "create_container", _fail)

    rolled_back: list[str] = []
    monkeypatch.setattr(
        podman_ops, "get_container", lambda client, cs_id: rolled_back.append(cs_id) or None
    )

    resp = client.post("/codespaces", json=_create_body())
    assert resp.status_code == 500
    assert rolled_back  # rollback attempted to find/remove the container


def test_create_rejects_invalid_repo(client: TestClient) -> None:
    resp = client.post(
        "/codespaces",
        json={"repo": "invalid", "login_pubkey": "ssh-ed25519 AAAA", "image": "img"},
    )
    assert resp.status_code == 422  # pydantic validation at the boundary


def test_list_codespaces(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    sample = shared.Codespace(
        id="abc",
        port=49207,
        user="dev",
        container_id="cid",
        repo="owner/name",
        workspace="default",
        workspace_dir="codespace-owner-name-default-deadbeef",
    )
    monkeypatch.setattr(podman_ops, "list_containers", lambda client: ["c"])
    monkeypatch.setattr(podman_ops, "to_codespace", lambda c: sample)

    resp = client.get("/codespaces")
    assert resp.status_code == 200
    assert resp.json()[0]["id"] == "abc"


def test_delete_missing_is_idempotent(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(podman_ops, "get_container", lambda client, cs_id: None)
    resp = client.request("DELETE", "/codespaces/nope")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "workspace_removed": False}


def test_delete_existing_removes_container(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    removed: list[object] = []
    monkeypatch.setattr(podman_ops, "get_container", lambda client, cs_id: object())
    monkeypatch.setattr(
        podman_ops,
        "read_label",
        lambda container, key: {shared.LABEL_REPO: "owner/name", shared.LABEL_WORKSPACE: "default"}[
            key
        ],
    )
    monkeypatch.setattr(podman_ops, "remove_container", lambda c: removed.append(c))
    purged: list[str] = []
    monkeypatch.setattr(podman_ops, "purge_workspace", lambda client, d: purged.append(d))

    resp = client.request("DELETE", "/codespaces/abc123")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "workspace_removed": False}
    assert len(removed) == 1  # container removed
    assert purged == []  # no purge without ?purge=true


def test_delete_with_purge_removes_workspace(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(podman_ops, "get_container", lambda client, cs_id: object())
    monkeypatch.setattr(
        podman_ops,
        "read_label",
        lambda container, key: {shared.LABEL_REPO: "owner/name", shared.LABEL_WORKSPACE: "default"}[
            key
        ],
    )
    monkeypatch.setattr(podman_ops, "remove_container", lambda c: None)
    purged: list[str] = []
    monkeypatch.setattr(podman_ops, "purge_workspace", lambda client, d: purged.append(d))

    resp = client.request("DELETE", "/codespaces/abc123?purge=true")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "workspace_removed": True}
    # purge target is <workspace_root>/<workspace_dir>
    assert purged == ["/var/lib/cs/" + shared.workspace_dir_name("owner/name", "default")]
