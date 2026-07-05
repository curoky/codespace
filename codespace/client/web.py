"""Local FastAPI Web GUI for managing codespaces across multiple agents."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Thread

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from codespace import shared
from codespace.client.config import load_config
from codespace.client.providers import provider_client
from codespace.client.service import (
    CodespaceService,
    CreateCodespaceInput,
    DeleteCodespaceResult,
)
from codespace.client.web_models import (
    ClearOperationsResponse,
    ConfigSummary,
    CreateCodespaceRequest,
    CreateCodespaceResponse,
    DashboardResponse,
    WebOperation,
)
from codespace.client.web_operations import OperationStore
from codespace.client.web_projection import (
    config_summary,
    dashboard_response,
    provider_for_delete,
)

STATIC_DIR = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)
GIT_ENV_MISSING_MESSAGE = (
    "{provider} token is not available in the Web GUI process; set {token_env} "
    "before starting `python -m codespace.client`, or configure {config_key}.token_env "
    "in config.yaml."
)


def create_app(config_path: str | Path | None = None) -> FastAPI:
    """Build the local Web GUI FastAPI app."""
    config = load_config(config_path)
    service = CodespaceService(config)
    operations = OperationStore()

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

    @app.get("/api/dashboard")
    def get_dashboard() -> DashboardResponse:
        return dashboard_response(service.list_all_agents(), operations.list())

    @app.post("/api/agents/{agent_id}/codespaces")
    def create_codespace(agent_id: str, req: CreateCodespaceRequest) -> CreateCodespaceResponse:
        if agent_id not in config.agents:
            raise HTTPException(status_code=404, detail="agent not found")
        git_provider = provider_client(config, req.provider)
        token = git_provider.token
        if not token:
            message = GIT_ENV_MISSING_MESSAGE.format(
                provider=git_provider.display_name,
                token_env=git_provider.token_env,
                config_key=git_provider.config_key,
            )
            logger.warning("Rejecting create codespace request for agent %s: %s", agent_id, message)
            raise HTTPException(status_code=400, detail=message)
        operation = operations.create(agent_id=agent_id, req=req)
        Thread(
            target=_run_create_operation,
            args=(operations, service, operation.id, agent_id, req, token),
            daemon=True,
        ).start()
        return CreateCodespaceResponse(operation_id=operation.id)

    @app.get("/api/operations/{operation_id}")
    def get_operation(operation_id: str) -> WebOperation:
        operation = operations.get(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="operation not found")
        return operation

    @app.delete("/api/operations")
    def clear_operations() -> ClearOperationsResponse:
        return ClearOperationsResponse(operations=operations.prune_completed())

    @app.delete("/api/agents/{agent_id}/codespaces/{codespace_id}")
    def delete_codespace(
        agent_id: str,
        codespace_id: str,
        purge: bool = Query(False),
        repo: str | None = Query(None),
    ) -> DeleteCodespaceResult:
        provider = provider_for_delete(config, agent_id, codespace_id, repo)
        token = provider_client(config, provider).token
        try:
            return service.delete_codespace(
                agent_id, codespace_id, token=token, repo=repo, provider=provider, purge=purge
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
            CreateCodespaceInput.model_validate(req.model_dump()),
            token=token,
            progress=_progress,
        )
        operations.update(operation_id, status="succeeded", stage="ready")
    except Exception as exc:
        operations.update(operation_id, status="failed", stage="failed", error=str(exc))
