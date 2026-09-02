"""Tests for current-operation state keyed by project and instance."""

import pytest

from controller.models import Operation, environment_id
from controller.operations import OperationStore


def _operation() -> Operation:
    return Operation(
        id=environment_id("home", "devspace", "debug"),
        host="home",
        workspace="devspace",
        instance="debug",
        status="queued",
        stage="queued",
    )


def test_store_rejects_concurrent_operation_and_retains_failure() -> None:
    store = OperationStore[Operation]()
    operation = store.create(_operation())

    with pytest.raises(RuntimeError, match="already running"):
        store.create(_operation())

    store.update(
        "home",
        operation.id,
        status="failed",
        stage="failed",
        error="podman unavailable",
    )

    operation = store.list()[0]
    assert operation.status == "failed"
    assert operation.error == "podman unavailable"


def test_retry_replaces_failed_operation_and_success_removes_it() -> None:
    store = OperationStore[Operation]()
    operation = store.create(_operation())
    store.update("home", operation.id, status="failed", error="first failure")

    retried = store.create(_operation())

    assert retried.status == "queued"
    assert retried.error is None
    store.remove("home", operation.id)
    assert store.list() == []


def test_dismiss_only_removes_failed_operation() -> None:
    store = OperationStore[Operation]()
    operation = store.create(_operation())

    with pytest.raises(RuntimeError, match="is still queued"):
        store.dismiss_failed("home", operation.id)

    store.update("home", operation.id, status="failed")

    assert store.dismiss_failed("home", operation.id) is True
    assert store.dismiss_failed("home", operation.id) is False
    assert store.list() == []
