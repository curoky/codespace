"""Tests for current-operation state keyed by project and instance."""

import pytest

from controller.operations import OperationStore


def test_store_rejects_concurrent_operation_and_retains_failure() -> None:
    store = OperationStore()
    store.create("home", "devspace", "debug")

    with pytest.raises(RuntimeError, match="already running"):
        store.create("home", "devspace", "debug")

    store.update(
        "home",
        "devspace",
        "debug",
        status="failed",
        stage="failed",
        error="podman unavailable",
    )

    operation = store.list()[0]
    assert operation.status == "failed"
    assert operation.error == "podman unavailable"


def test_retry_replaces_failed_operation_and_success_removes_it() -> None:
    store = OperationStore()
    store.create("home", "devspace", "debug")
    store.update("home", "devspace", "debug", status="failed", error="first failure")

    retried = store.create("home", "devspace", "debug")

    assert retried.status == "queued"
    assert retried.error is None
    store.remove("home", "devspace", "debug")
    assert store.list() == []


def test_dismiss_only_removes_failed_operation() -> None:
    store = OperationStore()
    store.create("home", "devspace", "debug")

    with pytest.raises(RuntimeError, match="is still queued"):
        store.dismiss_failed("home", "devspace", "debug")

    store.update("home", "devspace", "debug", status="failed")

    assert store.dismiss_failed("home", "devspace", "debug") is True
    assert store.dismiss_failed("home", "devspace", "debug") is False
    assert store.list() == []
