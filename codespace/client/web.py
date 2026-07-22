"""Local FastAPI Web GUI for managing codespaces across multiple agents."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from codespace import shared
from codespace.client.config import load_config
from codespace.client.service import (
    CodespaceService,
    DeleteCodespaceResult,
)
from codespace.client.web_models import (
    ConfigSummary,
    CreateCodespaceRequest,
    CreateCodespaceResponse,
    DashboardResponse,
    ProviderTokenStatus,
    TokenStatusResponse,
    UpdateProviderTokenRequest,
    WebOperation,
)
from codespace.client.web_operations import OperationStore
from codespace.client.web_projection import (
    config_summary,
    dashboard_response,
    provider_for_delete,
)

STATIC_DIR = Path(__file__).parent / "static"
COMPLETED_OPERATION_TTL_S = 30 * 60.0
OPERATION_STREAM_INTERVAL_S = 1.0


def _provider_token_status(provider_tokens: dict[shared.GitProvider, str]) -> TokenStatusResponse:
    """Return token presence without exposing token values."""
    return TokenStatusResponse(
        github=ProviderTokenStatus(has_token="github" in provider_tokens),
        gitlab=ProviderTokenStatus(has_token="gitlab" in provider_tokens),
    )


def create_app(config_path: str | Path | None = None) -> FastAPI:
    """Build the local Web GUI FastAPI app."""
    config = load_config(config_path)
    service = CodespaceService(config)
    operations = OperationStore(completed_ttl_s=COMPLETED_OPERATION_TTL_S)
    provider_tokens: dict[shared.GitProvider, str] = {}
    provider_tokens_lock = Lock()

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            service.close()

    app = FastAPI(title="codespace-web", lifespan=_lifespan)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(HTTPException)
    def _render_error(_request: object, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=shared.ErrorResponse(error=str(exc.detail)).model_dump(),
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    def get_config() -> ConfigSummary:
        return config_summary(config)

    @app.get("/api/provider-tokens")
    def get_provider_tokens() -> TokenStatusResponse:
        with provider_tokens_lock:
            return _provider_token_status(provider_tokens)

    @app.put("/api/provider-tokens/{provider}")
    def update_provider_token(
        provider: shared.GitProvider, req: UpdateProviderTokenRequest
    ) -> TokenStatusResponse:
        with provider_tokens_lock:
            provider_tokens[provider] = req.token
            return _provider_token_status(provider_tokens)

    @app.get("/api/dashboard")
    def get_dashboard() -> DashboardResponse:
        return dashboard_response(
            service.list_all_agents(),
            operations.list(),
        )

    @app.post("/api/agents/{agent_id}/codespaces")
    def create_codespace(
        agent_id: str,
        req: CreateCodespaceRequest,
        background_tasks: BackgroundTasks,
    ) -> CreateCodespaceResponse:
        if agent_id not in config.agents:
            raise HTTPException(status_code=404, detail="agent not found")
        with provider_tokens_lock:
            token = provider_tokens.get(req.provider)
        if token is None:
            raise HTTPException(status_code=400, detail=f"{req.provider} token is not set")
        operation = operations.create(agent_id=agent_id, req=req)
        background_tasks.add_task(
            _run_create_operation,
            operations,
            service,
            operation.id,
            agent_id,
            req,
            token,
        )
        return CreateCodespaceResponse(operation_id=operation.id)

    @app.get("/api/operations/stream")
    async def stream_operations() -> StreamingResponse:
        """Push operation changes to the browser as Server-Sent Events.

        The generator snapshots ``operations.list()`` (thread-safe) once per
        interval and only emits operations whose ``updated_at`` changed, so
        unchanged operations skip serialization entirely. The first frame sends
        the full current set so a late subscriber catches up. This trades ~1s
        latency for keeping the threaded create workers and the store untouched
        (no cross-thread event loop plumbing).
        """

        async def _events() -> AsyncIterator[str]:
            seen: dict[str, float] = {}
            while True:
                for operation in operations.list():
                    if seen.get(operation.id) != operation.updated_at:
                        seen[operation.id] = operation.updated_at
                        yield f"data: {operation.model_dump_json()}\n\n"
                await asyncio.sleep(OPERATION_STREAM_INTERVAL_S)

        return StreamingResponse(_events(), media_type="text/event-stream")

    @app.get("/api/operations/{operation_id}")
    def get_operation(operation_id: str) -> WebOperation:
        operation = operations.get(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="operation not found")
        return operation

    @app.delete("/api/agents/{agent_id}/codespaces/{codespace_id}")
    def delete_codespace(
        agent_id: str,
        codespace_id: str,
        purge: Annotated[bool, Query()] = False,
        repo: Annotated[str | None, Query()] = None,
        provider: Annotated[shared.GitProvider | None, Query()] = None,
    ) -> DeleteCodespaceResult:
        delete_provider = provider or provider_for_delete(config, agent_id, codespace_id, repo)
        with provider_tokens_lock:
            token = provider_tokens.get(delete_provider)
        try:
            return service.delete_codespace(
                agent_id,
                codespace_id,
                token=token,
                repo=repo,
                provider=delete_provider,
                purge=purge,
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


def _run_create_operation(
    operations: OperationStore,
    service: CodespaceService,
    operation_id: str,
    agent_id: str,
    req: CreateCodespaceRequest,
    token: str,
) -> None:
    def _progress(stage: str) -> None:
        operations.update(operation_id, status="running", stage=stage)

    try:
        operations.update(operation_id, status="running", stage="starting")
        service.create_codespace(
            agent_id,
            req,
            token=token,
            progress=_progress,
        )
        operations.update(operation_id, status="succeeded", stage="ready")
    except Exception as exc:
        operations.update(operation_id, status="failed", stage="failed", error=str(exc))
