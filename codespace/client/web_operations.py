"""In-memory operation store for the local Web GUI."""

from __future__ import annotations

import secrets
import time
from builtins import list as builtins_list
from threading import Lock

from cachetools import TTLCache

from codespace.client.service import instance_alias
from codespace.client.web_models import CreateCodespaceRequest, WebOperation, WebOperationStatus

_BUSY_STATUSES: set[WebOperationStatus] = {"queued", "running"}
_COMPLETED_OPERATION_LIMIT = 10_000


class OperationStore:
    """Thread-safe in-memory store for Web GUI operations."""

    def __init__(self, *, completed_ttl_s: float = float("inf")) -> None:
        self._busy: dict[str, WebOperation] = {}
        self._completed: TTLCache[str, WebOperation] = TTLCache(
            maxsize=_COMPLETED_OPERATION_LIMIT,
            ttl=completed_ttl_s,
            timer=lambda: time.time(),
        )
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
            self._busy[operation.id] = operation
        return operation

    def get(self, operation_id: str) -> WebOperation | None:
        with self._lock:
            return self._busy.get(operation_id) or self._completed.get(operation_id)

    def list(self) -> builtins_list[WebOperation]:
        with self._lock:
            return self._sorted_locked()

    def prune_completed(self) -> builtins_list[WebOperation]:
        """Remove non-busy operations and return the remaining operations."""
        with self._lock:
            self._completed.clear()
            return self._sorted_locked()

    def update(
        self,
        operation_id: str,
        *,
        status: WebOperationStatus | None = None,
        stage: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            operation = self._busy.get(operation_id) or self._completed[operation_id]
            updated = operation.model_copy(
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
            if updated.status in _BUSY_STATUSES:
                self._completed.pop(operation_id, None)
                self._busy[operation_id] = updated
            else:
                self._busy.pop(operation_id, None)
                self._completed[operation_id] = updated

    def _sorted_locked(self) -> builtins_list[WebOperation]:
        operations = [*self._busy.values(), *self._completed.values()]
        return sorted(operations, key=lambda op: op.created_at, reverse=True)
