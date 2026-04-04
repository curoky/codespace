"""Thread-safe process-local operation state."""

from __future__ import annotations

from threading import Lock

from controller.models import DeploymentOperation, Operation, OperationStatus


class OperationStore[OperationModel: (Operation, DeploymentOperation)]:
    """Track one operation per host and deterministic resource ID."""

    def __init__(self) -> None:
        self._operations: dict[tuple[str, str], OperationModel] = {}
        self._lock = Lock()

    def create(self, operation: OperationModel) -> OperationModel:
        """Replace failed state while rejecting concurrent work."""
        key = (operation.host, operation.id)
        with self._lock:
            existing = self._operations.get(key)
            if existing is not None and existing.status in {"queued", "running"}:
                raise RuntimeError(
                    f"operation already running for {operation.id!r} on host {operation.host!r}"
                )
            self._operations[key] = operation
        return operation

    def update(
        self,
        host: str,
        resource_id: str,
        *,
        status: OperationStatus | None = None,
        stage: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            operation = self._operations[(host, resource_id)]
            updates = {
                key: value
                for key, value in {"status": status, "stage": stage, "error": error}.items()
                if value is not None
            }
            self._operations[(host, resource_id)] = operation.model_copy(update=updates)

    def remove(self, host: str, resource_id: str) -> None:
        with self._lock:
            self._operations.pop((host, resource_id), None)

    def dismiss_failed(self, host: str, resource_id: str) -> bool:
        with self._lock:
            key = (host, resource_id)
            operation = self._operations.get(key)
            if operation is None:
                return False
            if operation.status != "failed":
                raise RuntimeError(
                    f"operation for {resource_id!r} on host {host!r} is still {operation.status}"
                )
            del self._operations[key]
            return True

    def list(self) -> list[OperationModel]:
        with self._lock:
            return [operation for _, operation in sorted(self._operations.items())]
