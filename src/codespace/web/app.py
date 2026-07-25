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
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from codespace.config import CONFIG_PATH, Config, load_config
from codespace.control import ControlPlane
from codespace.operations import Operation, describe_error
from codespace.resources import HostId, Resource, ResourceConflict, ResourceId, ResourceNotFound
from codespace.web import dashboard as dashboard_view
from codespace.workspaces import GitProvider, RepoGitState, TokenString

STATIC_DIR = Path(__file__).parent / "static"
router = APIRouter()
ResourcePath = Annotated[ResourceId, ApiPath()]
HostPath = Annotated[HostId, ApiPath()]


class CreateWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: HostId
    workspace: ResourceId


class UpdateTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: TokenString = Field(repr=False)


class DeleteWorkspaceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purge: bool = False


def _control(request: Request) -> ControlPlane:
    return cast("ControlPlane", request.app.state.control)


@router.get("/api/dashboard")
def dashboard(request: Request) -> dict[str, object]:
    return dashboard_view.build(_control(request))


@router.put("/api/providers/{provider}/token")
def update_token(
    provider: GitProvider,
    payload: UpdateTokenRequest,
    request: Request,
) -> dict[GitProvider, bool]:
    control = _control(request)
    control.set_token(provider, payload.token)
    return control.token_status()


@router.post("/api/projects/{project}/workspaces", status_code=202)
def create_workspace(
    project: ResourcePath,
    payload: CreateWorkspaceRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> Operation:
    control = _control(request)
    resource = Resource(payload.host, payload.workspace, project)
    operation = control.queue(resource)
    background_tasks.add_task(control.deploy, resource)
    return operation


@router.get("/api/projects/{project}/hosts/{host}/workspaces/{workspace}/logs")
def workspace_logs(
    project: ResourcePath,
    host: HostPath,
    workspace: ResourcePath,
    request: Request,
) -> dict[str, str]:
    return {"logs": _control(request).logs(Resource(host, workspace, project))}


@router.get("/api/projects/{project}/hosts/{host}/workspaces/{workspace}/tunnels/{port}")
def open_workspace_tunnel(
    project: ResourcePath,
    host: HostPath,
    workspace: ResourcePath,
    port: Annotated[int, ApiPath(ge=1, le=65535)],
    request: Request,
) -> RedirectResponse:
    local_port = _control(request).open_tunnel(Resource(host, workspace, project), port)
    return RedirectResponse(f"http://127.0.0.1:{local_port}/", status_code=303)


@router.get("/api/projects/{project}/hosts/{host}/workspaces/{workspace}/deletion-check")
def inspect_workspace_deletion(
    project: ResourcePath,
    host: HostPath,
    workspace: ResourcePath,
    request: Request,
) -> RepoGitState:
    return _control(request).inspect_deletion(Resource(host, workspace, project))


@router.delete("/api/projects/{project}/hosts/{host}/workspaces/{workspace}")
def delete_workspace(
    project: ResourcePath,
    host: HostPath,
    workspace: ResourcePath,
    request: Request,
    query: Annotated[DeleteWorkspaceQuery, Query()],
) -> dict[str, bool]:
    _control(request).remove(Resource(host, workspace, project), purge=query.purge)
    return {"deleted": True, "data_removed": query.purge}


@router.delete("/api/projects/{project}/hosts/{host}/operations/{workspace}")
def dismiss_workspace_operation(
    project: ResourcePath,
    host: HostPath,
    workspace: ResourcePath,
    request: Request,
) -> dict[str, bool]:
    dismissed = _control(request).dismiss_failed(Resource(host, workspace, project))
    return {"dismissed": dismissed}


@router.post("/api/services/{service}/hosts/{host}/apply", status_code=202)
def apply_service(
    service: ResourcePath,
    host: HostPath,
    background_tasks: BackgroundTasks,
    request: Request,
) -> Operation:
    control = _control(request)
    resource = Resource(host, service)
    operation = control.queue(resource)
    background_tasks.add_task(control.deploy, resource)
    return operation


@router.get("/api/services/{service}/hosts/{host}/logs")
def service_logs(
    service: ResourcePath,
    host: HostPath,
    request: Request,
) -> dict[str, str]:
    return {"logs": _control(request).logs(Resource(host, service))}


@router.get("/api/services/{service}/hosts/{host}/tunnels/{port}")
def open_service_tunnel(
    service: ResourcePath,
    host: HostPath,
    port: Annotated[int, ApiPath(ge=1, le=65535)],
    request: Request,
) -> RedirectResponse:
    local_port = _control(request).open_tunnel(Resource(host, service), port)
    return RedirectResponse(f"http://127.0.0.1:{local_port}/", status_code=303)


@router.delete("/api/services/{service}/hosts/{host}")
def remove_service(
    service: ResourcePath,
    host: HostPath,
    request: Request,
    purge: Annotated[bool, Query()] = False,
) -> dict[str, bool]:
    removed = _control(request).remove(Resource(host, service), purge=purge)
    return {"removed": removed, "data_removed": purge}


@router.delete("/api/services/{service}/hosts/{host}/operation")
def dismiss_service_operation(
    service: ResourcePath,
    host: HostPath,
    request: Request,
) -> dict[str, bool]:
    dismissed = _control(request).dismiss_failed(Resource(host, service))
    return {"dismissed": dismissed}


def _error(_request: Request, exc: Exception) -> JSONResponse:
    match exc:
        case ResourceNotFound():
            status, detail = 404, str(exc)
        case ResourceConflict():
            status, detail = 409, str(exc)
        case StarletteHTTPException():
            status, detail = exc.status_code, str(exc.detail)
        case RequestValidationError():
            status = 422
            detail = "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
                for item in exc.errors()
            )
        case _:
            status, detail = 500, describe_error(exc)
    return JSONResponse(status_code=status, content={"error": detail})


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
    for error_type in (
        StarletteHTTPException,
        ResourceNotFound,
        ResourceConflict,
        RequestValidationError,
        Exception,
    ):
        app.add_exception_handler(error_type, _error)
    app.add_api_route("/", _index, methods=["GET"])
    app.include_router(router)
    return app
