"""Local-only FastAPI application for Codespace."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi import Path as ApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from codespace.client.config import CONFIG_PATH, Config, load_config
from codespace.client.models import (
    CreateInstanceRequest,
    DashboardResponse,
    DeleteInstanceResult,
    GitProvider,
    Operation,
    UpdateTokenRequest,
)
from codespace.client.service import CodespaceService, describe_error

STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    config: Config | None = None,
    *,
    service: CodespaceService | None = None,
) -> FastAPI:
    """Build the single-process local application."""
    resolved_config = config or load_config(CONFIG_PATH)
    resolved_service = service or CodespaceService(resolved_config)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            resolved_service.close()

    app = FastAPI(
        title="codespace",
        lifespan=_lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.service = resolved_service
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(StarletteHTTPException)
    def _http_error(_request: object, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": str(exc.detail)},
        )

    @app.exception_handler(RequestValidationError)
    def _validation_error(_request: object, exc: RequestValidationError) -> JSONResponse:
        errors = []
        for error in exc.errors():
            location = ".".join(str(item) for item in error["loc"])
            errors.append(f"{location}: {error['msg']}")
        return JSONResponse(
            status_code=422,
            content={"error": "; ".join(errors)},
        )

    @app.exception_handler(Exception)
    def _unexpected_error(_request: object, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"error": describe_error(exc)})

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/dashboard")
    def dashboard() -> DashboardResponse:
        return resolved_service.dashboard()

    @app.put("/api/tokens/{provider}")
    def update_token(
        provider: GitProvider,
        request: UpdateTokenRequest,
    ) -> dict[GitProvider, bool]:
        resolved_service.set_token(provider, request.token)
        return resolved_service.token_status()

    @app.post(
        "/api/projects/{project}/instances",
        status_code=202,
    )
    def create_instance(
        project: Annotated[
            str,
            ApiPath(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$"),
        ],
        request: CreateInstanceRequest,
        background_tasks: BackgroundTasks,
    ) -> Operation:
        try:
            operation = resolved_service.queue_create(project, request.instance)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        background_tasks.add_task(
            resolved_service.create,
            project,
            request.instance,
        )
        return operation

    @app.delete("/api/projects/{project}/instances/{instance}")
    def delete_instance(
        project: Annotated[
            str,
            ApiPath(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$"),
        ],
        instance: Annotated[
            str,
            ApiPath(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$"),
        ],
        purge: Annotated[bool, Query()] = False,
        force: Annotated[bool, Query()] = False,
    ) -> DeleteInstanceResult:
        try:
            state = resolved_service.delete(project, instance, purge=purge, force=force)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
        except Exception as exc:
            raise HTTPException(status_code=409, detail=describe_error(exc)) from exc
        return DeleteInstanceResult(
            deleted=force,
            workspace_removed=purge and force,
            state=state,
        )

    return app
