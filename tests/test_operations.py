"""Tests for the shared Workspace and Service operation store."""

import pytest

from codespace.operations import Operation, OperationStore, describe_error


def _operation(*, status: str = "queued") -> Operation:
    return Operation(
        id="codespace-workspace-home-codespace-debug",
        kind="workspace",
        host="home",
        resource="debug",
        project="codespace",
        status=status,  # type: ignore[arg-type]
        stage=status,
    )


def test_store_rejects_concurrent_operation_and_retains_failure() -> None:
    store = OperationStore()
    operation = store.create(_operation())

    with pytest.raises(RuntimeError, match="already running"):
        store.create(_operation())

    store.update(
        operation.host,
        operation.id,
        status="failed",
        stage="failed",
        error="boom",
    )

    assert store.list()[0].error == "boom"


def test_failed_operation_can_be_replaced_and_dismissed() -> None:
    store = OperationStore()
    operation = store.create(_operation(status="failed"))

    replacement = store.create(_operation())
    assert replacement.status == "queued"

    with pytest.raises(RuntimeError, match="still queued"):
        store.dismiss_failed(operation.host, operation.id)

    store.update(operation.host, operation.id, status="failed")
    assert store.dismiss_failed(operation.host, operation.id) is True
    assert store.dismiss_failed(operation.host, operation.id) is False


def test_describe_error_includes_cause_chain() -> None:
    try:
        try:
            raise TimeoutError("timed out")
        except TimeoutError as inner:
            raise RuntimeError("request failed") from inner
    except RuntimeError as exc:
        assert describe_error(exc) == "RuntimeError: request failed <- TimeoutError: timed out"
