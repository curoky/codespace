"""Thread-safe process-local lifecycle operation state."""

from __future__ import annotations

from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict

type OperationStatus = Literal["queued", "running", "failed"]
type OperationKind = Literal["workspace", "service"]


def describe_error(exc: BaseException) -> str:
    """Render an exception and its cause chain without repeating messages."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip()
        rendered = f"{type(current).__name__}: {text}" if text else type(current).__name__
        if rendered not in parts:
            parts.append(rendered)
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)


class Operation(BaseModel):
    """One in-flight or failed lifecycle operation."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: OperationKind
    host: str
    resource: str
    project: str | None = None
    status: OperationStatus
    stage: str
    error: str | None = None


class OperationStore:
    """Track one operation per Host and deterministic resource identity."""

    def __init__(self) -> None:
        self._operations: dict[tuple[str, str], Operation] = {}
        self._lock = Lock()

    def create(self, operation: Operation) -> Operation:
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

    def list(self) -> list[Operation]:
        with self._lock:
            return [operation for _, operation in sorted(self._operations.items())]
