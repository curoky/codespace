"""Thread-safe process-local operation state."""

from __future__ import annotations

from threading import Lock

from codespace.client.models import Operation, OperationStatus, environment_id


class OperationStore:
    """Keep the current operation for each project instance on each host."""

    def __init__(self) -> None:
        self._operations: dict[tuple[str, str, str], Operation] = {}
        self._lock = Lock()

    def create(self, host: str, project: str, instance: str) -> Operation:
        """Replace failed state and queue an operation for one identity."""
        operation = Operation(
            id=environment_id(host, project, instance),
            host=host,
            project=project,
            instance=instance,
            status="queued",
            stage="queued",
        )
        key = (host, project, instance)
        with self._lock:
            existing = self._operations.get(key)
            if existing is not None and existing.status in {"queued", "running"}:
                raise RuntimeError(
                    f"operation already running for project {project!r} instance {instance!r} "
                    f"on host {host!r}"
                )
            self._operations[key] = operation
        return operation

    def update(
        self,
        host: str,
        project: str,
        instance: str,
        *,
        status: OperationStatus | None = None,
        stage: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update only supplied fields on an existing operation."""
        key = (host, project, instance)
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

    def remove(self, host: str, project: str, instance: str) -> None:
        """Remove a successful operation once inventory is authoritative."""
        with self._lock:
            self._operations.pop((host, project, instance), None)

    def list(self) -> list[Operation]:
        """Return operations in stable host, project and instance order."""
        with self._lock:
            return sorted(
                self._operations.values(),
                key=lambda operation: (operation.host, operation.project, operation.instance),
            )
