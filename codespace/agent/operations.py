"""Thread-safe in-memory store for agent create operations.

The agent tracks each asynchronous create as a ``shared.CreateOperation`` and
exposes it over ``GET /operations/{id}``. This mirrors the client's
``web_operations.OperationStore`` so both sides manage operation state the same
way. State is process-local: an agent restart drops operation history, but
codespaces are rediscovered from podman labels (DESIGN.md §11).
"""

from threading import Lock

from codespace import shared


class OperationStore:
    """Thread-safe in-memory store for agent create operations."""

    def __init__(self) -> None:
        self._operations: dict[str, shared.CreateOperation] = {}
        self._lock = Lock()

    def create(self, operation_id: str) -> shared.CreateOperation:
        """Register a new queued operation and return it."""
        operation = shared.CreateOperation(id=operation_id, status="queued", stage="queued")
        with self._lock:
            self._operations[operation_id] = operation
        return operation

    def get(self, operation_id: str) -> shared.CreateOperation | None:
        with self._lock:
            return self._operations.get(operation_id)

    def update(
        self,
        operation_id: str,
        *,
        status: shared.CreateOperationStatus | None = None,
        stage: str | None = None,
        codespace: shared.Codespace | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            operation = self._operations[operation_id]
            self._operations[operation_id] = operation.model_copy(
                update={
                    key: value
                    for key, value in {
                        "status": status,
                        "stage": stage,
                        "codespace": codespace,
                        "error": error,
                    }.items()
                    if value is not None
                }
            )
