"""Local-only FastAPI application for Codespace.

Routes call the service directly and let exceptions propagate: the global
handlers map ``KeyError`` to 404 and ``RuntimeError`` to 409, so no route
repeats that translation.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, BackgroundTasks, FastAPI, Query, Request
from fastapi import Path as ApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from controller.config import CONFIG_PATH, Config, load_config
from controller.models import (
    ContainerLogsResult,
    CreateInstanceRequest,
    DashboardResponse,
    DeleteDeploymentResult,
    DeleteInstanceResult,
    DeploymentOperation,
    GitProvider,
    Operation,
    UpdateTokenRequest,
)
from controller.service import CodespaceService, describe_error

STATIC_DIR = Path(__file__).parent / "static"

router = APIRouter()
ResourcePath = Annotated[str, ApiPath(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")]
HostPath = Annotated[str, ApiPath(pattern=r"^[a-z0-9][a-z0-9.-]{0,62}$")]


def _service(request: Request) -> CodespaceService:
    return cast("CodespaceService", request.app.state.service)


@router.get("/api/dashboard")
def dashboard(request: Request) -> DashboardResponse:
    return _service(request).dashboard()


@router.put("/api/tokens/{provider}")
def update_token(
    provider: GitProvider,
    payload: UpdateTokenRequest,
    request: Request,
) -> dict[GitProvider, bool]:
    service = _service(request)
    service.set_token(provider, payload.token)
    return service.token_status()


@router.post("/api/workspaces/{workspace}/instances", status_code=202)
def create_instance(
    workspace: ResourcePath,
    payload: CreateInstanceRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> Operation:
    service = _service(request)
    operation = service.queue_create(workspace, payload.host, payload.instance)
    background_tasks.add_task(service.create, workspace, payload.host, payload.instance)
    return operation


@router.delete("/api/workspaces/{workspace}/hosts/{host}/operations/{instance}")
def dismiss_failed_operation(
    workspace: ResourcePath,
    host: HostPath,
    instance: ResourcePath,
    request: Request,
) -> dict[str, bool]:
    dismissed = _service(request).dismiss_failed_operation(workspace, host, instance)
    return {"dismissed": dismissed}


@router.get("/api/workspaces/{workspace}/hosts/{host}/instances/{instance}/logs")
def instance_logs(
    workspace: ResourcePath,
    host: HostPath,
    instance: ResourcePath,
    request: Request,
) -> ContainerLogsResult:
    return ContainerLogsResult(logs=_service(request).logs(workspace, host, instance))


@router.delete("/api/workspaces/{workspace}/hosts/{host}/instances/{instance}")
def delete_instance(
    workspace: ResourcePath,
    host: HostPath,
    instance: ResourcePath,
    request: Request,
    purge: Annotated[bool, Query()] = False,
    force: Annotated[bool, Query()] = False,
) -> DeleteInstanceResult:
    state = _service(request).delete(workspace, host, instance, purge=purge, force=force)
    return DeleteInstanceResult(
        deleted=force,
        workspace_removed=purge and force,
        state=state,
    )


@router.post("/api/deployments/{deployment}/hosts/{host}/deploy", status_code=202)
def deploy_deployment(
    deployment: ResourcePath,
    host: HostPath,
    background_tasks: BackgroundTasks,
    request: Request,
) -> DeploymentOperation:
    service = _service(request)
    operation = service.queue_deploy(deployment, host)
    background_tasks.add_task(service.deploy, deployment, host)
    return operation


@router.delete("/api/deployments/{deployment}/hosts/{host}")
def clean_deployment(
    deployment: ResourcePath,
    host: HostPath,
    request: Request,
    purge: Annotated[bool, Query()] = False,
) -> DeleteDeploymentResult:
    removed = _service(request).clean_deployment(deployment, host, purge=purge)
    return DeleteDeploymentResult(removed=removed, data_removed=purge)


@router.get("/api/deployments/{deployment}/hosts/{host}/logs")
def deployment_logs(
    deployment: ResourcePath,
    host: HostPath,
    request: Request,
) -> ContainerLogsResult:
    return ContainerLogsResult(logs=_service(request).deployment_logs(deployment, host))


@router.delete("/api/deployments/{deployment}/hosts/{host}/operations")
def dismiss_failed_deployment_operation(
    deployment: ResourcePath,
    host: HostPath,
    request: Request,
) -> dict[str, bool]:
    dismissed = _service(request).dismiss_failed_deployment_operation(deployment, host)
    return {"dismissed": dismissed}


def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("StarletteHTTPException", exc)
    return JSONResponse(status_code=error.status_code, content={"error": str(error.detail)})


def _not_found(_request: Request, exc: Exception) -> JSONResponse:
    """A service ``KeyError`` names an unknown workspace, host or deployment."""
    return JSONResponse(status_code=404, content={"error": str(exc.args[0]) if exc.args else ""})


def _conflict(_request: Request, exc: Exception) -> JSONResponse:
    """A service ``RuntimeError`` reports a state conflict the caller can resolve."""
    return JSONResponse(status_code=409, content={"error": str(exc)})


def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("RequestValidationError", exc)
    errors = [
        f"{'.'.join(str(item) for item in item['loc'])}: {item['msg']}" for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={"error": "; ".join(errors)})


def _unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": describe_error(exc)})


def _index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


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
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(KeyError, _not_found)
    app.add_exception_handler(RuntimeError, _conflict)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)
    app.add_api_route("/", _index, methods=["GET"])
    app.include_router(router)
    return app
