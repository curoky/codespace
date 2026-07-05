"""In-memory operation store for the local Web GUI."""

from __future__ import annotations

import secrets
import time
from builtins import list as builtins_list
from threading import Lock

from codespace.client.service import instance_alias
from codespace.client.web_models import CreateCodespaceRequest, WebOperation, WebOperationStatus


class OperationStore:
    """Thread-safe in-memory store for Web GUI operations."""

    def __init__(self) -> None:
        self._operations: dict[str, WebOperation] = {}
        self._lock = Lock()

    def create(self, *, agent_id: str, req: CreateCodespaceRequest) -> WebOperation:
        now = time.time()
        operation = WebOperation(
            id=secrets.token_hex(6),
            agent_id=agent_id,
            alias=instance_alias(agent_id, req.template, req.instance),
            repo=req.repo,
            provider=req.provider,
            template=req.template,
            instance=req.instance,
            status="queued",
            stage="queued",
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._operations[operation.id] = operation
        return operation

    def get(self, operation_id: str) -> WebOperation | None:
        with self._lock:
            return self._operations.get(operation_id)

    def list(self) -> builtins_list[WebOperation]:
        with self._lock:
            return sorted(self._operations.values(), key=lambda op: op.created_at, reverse=True)

    def prune_completed(self) -> builtins_list[WebOperation]:
        """Remove non-busy operations and return the remaining operations."""
        with self._lock:
            self._operations = {
                operation_id: operation
                for operation_id, operation in self._operations.items()
                if operation.status in {"queued", "running"}
            }
            return sorted(self._operations.values(), key=lambda op: op.created_at, reverse=True)

    def prune_completed_older_than(self, max_age_s: float) -> builtins_list[WebOperation]:
        """Remove completed operations older than ``max_age_s`` and return the rest."""
        cutoff = time.time() - max_age_s
        with self._lock:
            self._operations = {
                operation_id: operation
                for operation_id, operation in self._operations.items()
                if operation.status in {"queued", "running"} or operation.updated_at >= cutoff
            }
            return sorted(self._operations.values(), key=lambda op: op.created_at, reverse=True)

    def update(
        self,
        operation_id: str,
        *,
        status: WebOperationStatus | None = None,
        stage: str | None = None,
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
                        "error": error,
                        "updated_at": time.time(),
                    }.items()
                    if value is not None
                }
            )
