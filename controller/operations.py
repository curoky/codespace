"""Thread-safe process-local operation state."""

from __future__ import annotations

from threading import Lock

from controller.models import (
    DeploymentOperation,
    Operation,
    OperationStatus,
    deployment_id,
    environment_id,
)


class OperationStore:
    """Keep the current operation for each workspace instance on each host."""

    def __init__(self) -> None:
        self._operations: dict[tuple[str, str, str], Operation] = {}
        self._lock = Lock()

    def create(self, host: str, workspace: str, instance: str) -> Operation:
        """Replace failed state and queue an operation for one identity."""
        operation = Operation(
            id=environment_id(host, workspace, instance),
            host=host,
            workspace=workspace,
            instance=instance,
            status="queued",
            stage="queued",
        )
        key = (host, workspace, instance)
        with self._lock:
            existing = self._operations.get(key)
            if existing is not None and existing.status in {"queued", "running"}:
                raise RuntimeError(
                    f"operation already running for workspace {workspace!r} instance {instance!r} "
                    f"on host {host!r}"
                )
            self._operations[key] = operation
        return operation

    def update(
        self,
        host: str,
        workspace: str,
        instance: str,
        *,
        status: OperationStatus | None = None,
        stage: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update only supplied fields on an existing operation."""
        key = (host, workspace, instance)
        with self._lock:
            operation = self._operations[key]
            updates: dict[str, object] = {}
            if status is not None:
                updates["status"] = status
            if stage is not None:
                updates["stage"] = stage
            if error is not None:
                updates["error"] = error
            self._operations[key] = operation.model_copy(update=updates)

    def remove(self, host: str, workspace: str, instance: str) -> None:
        """Remove a successful operation once inventory is authoritative."""
        with self._lock:
            self._operations.pop((host, workspace, instance), None)

    def dismiss_failed(self, host: str, workspace: str, instance: str) -> bool:
        """Remove a failed operation without allowing active work to be hidden."""
        key = (host, workspace, instance)
        with self._lock:
            operation = self._operations.get(key)
            if operation is None:
                return False
            if operation.status != "failed":
                raise RuntimeError(
                    f"operation for workspace {workspace!r} instance {instance!r} "
                    f"on host {host!r} is still {operation.status}"
                )
            del self._operations[key]
            return True

    def list(self) -> list[Operation]:
        """Return operations in stable host, workspace and instance order."""
        with self._lock:
            return sorted(
                self._operations.values(),
                key=lambda operation: (operation.host, operation.workspace, operation.instance),
            )


class DeploymentOperationStore:
    """Keep the current async operation for each deployment on each host."""

    def __init__(self) -> None:
        self._operations: dict[tuple[str, str], DeploymentOperation] = {}
        self._lock = Lock()

    def create(self, host: str, deployment: str) -> DeploymentOperation:
        """Replace failed state and queue an operation for one deployment/host."""
        operation = DeploymentOperation(
            id=deployment_id(deployment),
            host=host,
            deployment=deployment,
            status="queued",
            stage="queued",
        )
        key = (host, deployment)
        with self._lock:
            existing = self._operations.get(key)
            if existing is not None and existing.status in {"queued", "running"}:
                raise RuntimeError(
                    f"operation already running for deployment {deployment!r} on host {host!r}"
                )
            self._operations[key] = operation
        return operation

    def update(
        self,
        host: str,
        deployment: str,
        *,
        status: OperationStatus | None = None,
        stage: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update only supplied fields on an existing deployment operation."""
        key = (host, deployment)
        with self._lock:
            operation = self._operations[key]
            updates: dict[str, object] = {}
            if status is not None:
                updates["status"] = status
            if stage is not None:
                updates["stage"] = stage
            if error is not None:
                updates["error"] = error
            self._operations[key] = operation.model_copy(update=updates)

    def remove(self, host: str, deployment: str) -> None:
        """Remove a successful operation once inventory is authoritative."""
        with self._lock:
            self._operations.pop((host, deployment), None)

    def dismiss_failed(self, host: str, deployment: str) -> bool:
        """Remove a failed operation without allowing active work to be hidden."""
        key = (host, deployment)
        with self._lock:
            operation = self._operations.get(key)
            if operation is None:
                return False
            if operation.status != "failed":
                raise RuntimeError(
                    f"operation for deployment {deployment!r} on host {host!r} "
                    f"is still {operation.status}"
                )
            del self._operations[key]
            return True

    def get(self, host: str, deployment: str) -> DeploymentOperation | None:
        """Return the current operation for one deployment/host, if any."""
        with self._lock:
            return self._operations.get((host, deployment))

    def list(self) -> list[DeploymentOperation]:
        """Return operations in stable host and deployment order."""
        with self._lock:
            return sorted(
                self._operations.values(),
                key=lambda operation: (operation.host, operation.deployment),
            )
