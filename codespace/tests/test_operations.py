"""Tests for the agent's in-memory operation store."""

from codespace import shared
from codespace.agent.operations import OperationStore


def test_create_registers_queued_operation() -> None:
    store = OperationStore()
    operation = store.create("op1")
    assert operation.id == "op1"
    assert operation.status == "queued"
    assert operation.stage == "queued"
    assert store.get("op1") is operation


def test_get_returns_none_for_unknown_id() -> None:
    assert OperationStore().get("missing") is None


def test_update_merges_only_provided_fields() -> None:
    store = OperationStore()
    store.create("op1")
    store.update("op1", status="running", stage="creating container")

    operation = store.get("op1")
    assert operation is not None
    assert operation.status == "running"
    assert operation.stage == "creating container"
    assert operation.error is None

    # A later update leaves untouched fields intact.
    store.update("op1", stage="waiting for ssh")
    operation = store.get("op1")
    assert operation is not None
    assert operation.status == "running"
    assert operation.stage == "waiting for ssh"


def test_update_can_attach_codespace_and_terminal_status() -> None:
    store = OperationStore()
    store.create("op1")
    codespace = shared.Codespace(
        id="cs1",
        port=49207,
        user="dev",
        container_id="cid",
        repo="owner/name",
        workspace_dir="codespace-owner-name-default-default-deadbeef",
    )
    store.update("op1", status="succeeded", stage="ready", codespace=codespace)

    operation = store.get("op1")
    assert operation is not None
    assert operation.status == "succeeded"
    assert operation.codespace is not None
    assert operation.codespace.id == "cs1"
