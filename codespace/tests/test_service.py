"""Tests for the codespace provisioner orchestration.

These exercise the create flow directly against fakes, without going through the
FastAPI layer: dedup rejection, rollback on failure, and stage ordering.
"""

import pytest

from codespace import shared
from codespace.agent import containers, credentials, keys
from codespace.agent.config import AgentConfig
from codespace.agent.operations import OperationStore
from codespace.agent.service import CodespaceProvisioner


class _DummyClient:
    def __enter__(self) -> "_DummyClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _config() -> AgentConfig:
    return AgentConfig(
        workspace_root_host="/var/lib/cs", podman_uri="unix:///run/podman/podman.sock"
    )


def _request() -> shared.CreateRequest:
    return shared.CreateRequest(
        repo="owner/name",
        login_pubkey="ssh-ed25519 AAAA",
        image="codespace/dev:latest",
    )


def _provisioner(operations: OperationStore) -> CodespaceProvisioner:
    return CodespaceProvisioner(_config(), operations, lambda: _DummyClient())


def _patch_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        keys,
        "generate_deploy_keypair",
        lambda: keys.DeployKeypair(private_openssh="PRIV", public_openssh="ssh-ed25519 PUB"),
    )
    monkeypatch.setattr(containers, "find_container_by_instance", lambda *a, **k: None)
    monkeypatch.setattr(containers, "ensure_workspace_dir", lambda *a: None)
    monkeypatch.setattr(containers, "pull_image", lambda *a: None)
    monkeypatch.setattr(
        containers,
        "create_container",
        lambda *a, **k: containers.ContainerInfo(container_id="cid", port=49207),
    )
    monkeypatch.setattr(credentials, "inject_credentials", lambda *a, **k: None)
    monkeypatch.setattr(containers, "wait_for_ssh_ready", lambda *a: None)


def test_provision_success_records_ready_codespace(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_happy_path(monkeypatch)
    operations = OperationStore()
    operations.create("op1")

    _provisioner(operations).provision("op1", "cs1", _request())

    operation = operations.get("op1")
    assert operation is not None
    assert operation.status == "succeeded"
    assert operation.stage == "ready"
    assert operation.codespace is not None
    assert operation.codespace.id == "cs1"
    assert operation.codespace.port == 49207
    assert operation.codespace.deploy_keys == [
        shared.DeployKeyRef(
            repo="owner/name",
            provider="github",
            public_openssh="ssh-ed25519 PUB",
            read_only=False,
        )
    ]


def test_provision_orders_workspace_before_pull_and_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        keys,
        "generate_deploy_keypair",
        lambda: keys.DeployKeypair(private_openssh="PRIV", public_openssh="ssh-ed25519 PUB"),
    )
    monkeypatch.setattr(containers, "find_container_by_instance", lambda *a, **k: None)
    monkeypatch.setattr(
        containers, "ensure_workspace_dir", lambda path: calls.append(f"mkdir:{path}")
    )
    monkeypatch.setattr(containers, "pull_image", lambda *a: calls.append("pull"))

    def _create(*a: object, **kwargs: object) -> containers.ContainerInfo:
        calls.append(f"create:{kwargs['workspace_host_dir']}")
        return containers.ContainerInfo(container_id="cid", port=49207)

    monkeypatch.setattr(containers, "create_container", _create)
    monkeypatch.setattr(credentials, "inject_credentials", lambda *a, **k: None)
    monkeypatch.setattr(containers, "wait_for_ssh_ready", lambda *a: None)

    operations = OperationStore()
    operations.create("op1")
    _provisioner(operations).provision("op1", "cs1", _request())

    workspace_dir = "/var/lib/cs/" + shared.workspace_dir_name("owner/name", "default", "default")
    assert calls == [f"mkdir:{workspace_dir}", "pull", f"create:{workspace_dir}"]


def test_provision_rejects_existing_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = object()
    created: list[object] = []
    monkeypatch.setattr(containers, "find_container_by_instance", lambda *a, **k: existing)
    monkeypatch.setattr(containers, "read_label", lambda container, key, default="": "abc123")
    monkeypatch.setattr(containers, "container_status", lambda container: None)
    monkeypatch.setattr(containers, "create_container", lambda *a, **k: created.append(k))
    monkeypatch.setattr(containers, "get_container", lambda *a: None)

    operations = OperationStore()
    operations.create("op1")
    _provisioner(operations).provision("op1", "cs1", _request())

    operation = operations.get("op1")
    assert operation is not None
    assert operation.status == "failed"
    assert operation.error == (
        "codespace already exists for repo/template/instance (id=abc123, name=None, status=unknown)"
    )
    assert created == []


def test_provision_failure_rolls_back_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        keys,
        "generate_deploy_keypair",
        lambda: keys.DeployKeypair(private_openssh="PRIV", public_openssh="PUB"),
    )
    monkeypatch.setattr(containers, "find_container_by_instance", lambda *a, **k: None)
    monkeypatch.setattr(containers, "ensure_workspace_dir", lambda *a: None)
    monkeypatch.setattr(containers, "pull_image", lambda *a: None)

    def _fail(*a: object, **k: object) -> containers.ContainerInfo:
        raise RuntimeError("podman down")

    monkeypatch.setattr(containers, "create_container", _fail)
    rolled_back: list[str] = []
    monkeypatch.setattr(
        containers, "get_container", lambda client, cs_id: rolled_back.append(cs_id) or None
    )

    operations = OperationStore()
    operations.create("op1")
    _provisioner(operations).provision("op1", "cs1", _request())

    operation = operations.get("op1")
    assert operation is not None
    assert operation.status == "failed"
    assert operation.error == "podman down"
    assert rolled_back == ["cs1"]  # rollback attempted to find/remove the container


def test_provision_failure_survives_rollback_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        keys,
        "generate_deploy_keypair",
        lambda: keys.DeployKeypair(private_openssh="PRIV", public_openssh="PUB"),
    )
    monkeypatch.setattr(containers, "find_container_by_instance", lambda *a, **k: None)
    monkeypatch.setattr(containers, "ensure_workspace_dir", lambda *a: None)
    monkeypatch.setattr(containers, "pull_image", lambda *a: None)

    def _raise_podman_down(*a: object, **k: object) -> containers.ContainerInfo:
        raise RuntimeError("podman down")

    def _raise_rollback_down(*a: object, **k: object) -> None:
        raise RuntimeError("rollback down")

    monkeypatch.setattr(containers, "create_container", _raise_podman_down)
    monkeypatch.setattr(containers, "get_container", _raise_rollback_down)

    operations = OperationStore()
    operations.create("op1")
    _provisioner(operations).provision("op1", "cs1", _request())

    operation = operations.get("op1")
    assert operation is not None
    assert operation.status == "failed"
    assert operation.error == "podman down"


def test_provision_rejects_concurrent_duplicate_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_happy_path(monkeypatch)
    operations = OperationStore()
    provisioner = _provisioner(operations)
    # Pre-reserve the instance slot so the next provision sees it as in-flight.
    provisioner._reserve_instance(("owner/name", "default", "default"))

    operations.create("op1")
    provisioner.provision("op1", "cs1", _request())

    operation = operations.get("op1")
    assert operation is not None
    assert operation.status == "failed"
    assert operation.error == "codespace creation is already running for repo/template/instance"
