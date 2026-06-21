"""Localhost-only HTTP boundary for the Codespace control plane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, BackgroundTasks, FastAPI, Query, Request
from fastapi import Path as ApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from codespace.config import CONFIG_PATH, Config, load_config
from codespace.control import ControlPlane
from codespace.errors import ResourceConflict, ResourceNotFound
from codespace.operations import Operation, describe_error
from codespace.web import dashboard as dashboard_view
from codespace.web.models import (
    ContainerLogsResponse,
    CreateWorkspaceRequest,
    DashboardResponse,
    DeleteWorkspaceQuery,
    DeleteWorkspaceResult,
    RemoveServiceResult,
    UpdateTokenRequest,
)
from codespace.workspaces.models import GitProvider, RepoGitState

STATIC_DIR = Path(__file__).parent / "static"
router = APIRouter()
ResourcePath = Annotated[str, ApiPath(pattern=r"^[a-z0-9][a-z0-9-]{0,31}$")]
HostPath = Annotated[str, ApiPath(pattern=r"^[a-z0-9][a-z0-9.-]{0,62}$")]


def _control(request: Request) -> ControlPlane:
    return cast("ControlPlane", request.app.state.control)


@router.get("/api/dashboard")
def dashboard(request: Request) -> DashboardResponse:
    return dashboard_view.build(_control(request))


@router.put("/api/providers/{provider}/token")
def update_token(
    provider: GitProvider,
    payload: UpdateTokenRequest,
    request: Request,
) -> dict[GitProvider, bool]:
    control = _control(request)
    control.tokens.set(provider, payload.token)
    return control.tokens.status()


@router.post("/api/projects/{project}/workspaces", status_code=202)
def create_workspace(
    project: ResourcePath,
    payload: CreateWorkspaceRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> Operation:
    manager = _control(request).workspaces
    operation = manager.queue_create(project, payload.host, payload.workspace)
    background_tasks.add_task(manager.create, project, payload.host, payload.workspace)
    return operation


@router.get("/api/projects/{project}/hosts/{host}/workspaces/{workspace}/logs")
def workspace_logs(
    project: ResourcePath,
    host: HostPath,
    workspace: ResourcePath,
    request: Request,
) -> ContainerLogsResponse:
    logs = _control(request).workspaces.logs(project, host, workspace)
    return ContainerLogsResponse(logs=logs)


@router.get("/api/projects/{project}/hosts/{host}/workspaces/{workspace}/tunnels/{port}")
def open_workspace_tunnel(
    project: ResourcePath,
    host: HostPath,
    workspace: ResourcePath,
    port: Annotated[int, ApiPath(ge=1, le=65535)],
    request: Request,
) -> RedirectResponse:
    local_port = _control(request).workspaces.open_tunnel(project, host, workspace, port)
    return RedirectResponse(f"http://127.0.0.1:{local_port}/", status_code=303)


@router.get("/api/projects/{project}/hosts/{host}/workspaces/{workspace}/deletion-check")
def inspect_workspace_deletion(
    project: ResourcePath,
    host: HostPath,
    workspace: ResourcePath,
    request: Request,
) -> RepoGitState:
    return _control(request).workspaces.inspect_deletion(project, host, workspace)


@router.delete("/api/projects/{project}/hosts/{host}/workspaces/{workspace}")
def delete_workspace(
    project: ResourcePath,
    host: HostPath,
    workspace: ResourcePath,
    request: Request,
    query: Annotated[DeleteWorkspaceQuery, Query()],
) -> DeleteWorkspaceResult:
    _control(request).workspaces.delete(
        project,
        host,
        workspace,
        purge=query.purge,
    )
    return DeleteWorkspaceResult(
        deleted=True,
        data_removed=query.purge,
    )


@router.delete("/api/projects/{project}/hosts/{host}/operations/{workspace}")
def dismiss_workspace_operation(
    project: ResourcePath,
    host: HostPath,
    workspace: ResourcePath,
    request: Request,
) -> dict[str, bool]:
    dismissed = _control(request).workspaces.dismiss_failed(project, host, workspace)
    return {"dismissed": dismissed}


@router.post("/api/services/{service}/hosts/{host}/apply", status_code=202)
def apply_service(
    service: ResourcePath,
    host: HostPath,
    background_tasks: BackgroundTasks,
    request: Request,
) -> Operation:
    manager = _control(request).services
    operation = manager.queue_apply(service, host)
    background_tasks.add_task(manager.apply, service, host)
    return operation


@router.get("/api/services/{service}/hosts/{host}/logs")
def service_logs(
    service: ResourcePath,
    host: HostPath,
    request: Request,
) -> ContainerLogsResponse:
    logs = _control(request).services.logs(service, host)
    return ContainerLogsResponse(logs=logs)


@router.delete("/api/services/{service}/hosts/{host}")
def remove_service(
    service: ResourcePath,
    host: HostPath,
    request: Request,
    purge: Annotated[bool, Query()] = False,
) -> RemoveServiceResult:
    removed = _control(request).services.remove(service, host, purge=purge)
    return RemoveServiceResult(removed=removed, data_removed=purge)


@router.delete("/api/services/{service}/hosts/{host}/operation")
def dismiss_service_operation(
    service: ResourcePath,
    host: HostPath,
    request: Request,
) -> dict[str, bool]:
    dismissed = _control(request).services.dismiss_failed(service, host)
    return {"dismissed": dismissed}


def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("StarletteHTTPException", exc)
    return JSONResponse(status_code=error.status_code, content={"error": str(error.detail)})


def _not_found(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": str(exc)})


def _conflict(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=409, content={"error": str(exc)})


def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    error = cast("RequestValidationError", exc)
    details = [
        f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in error.errors()
    ]
    return JSONResponse(status_code=422, content={"error": "; ".join(details)})


def _unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": describe_error(exc)})


def _index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def create_app(
    config: Config | None = None,
    *,
    control: ControlPlane | None = None,
) -> FastAPI:
    resolved_config = config or load_config(CONFIG_PATH)
    resolved_control = control or ControlPlane(resolved_config)

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            resolved_control.close()

    app = FastAPI(
        title="codespace",
        lifespan=_lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.control = resolved_control
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(ResourceNotFound, _not_found)
    app.add_exception_handler(ResourceConflict, _conflict)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unexpected_error)
    app.add_api_route("/", _index, methods=["GET"])
    app.include_router(router)
    return app
