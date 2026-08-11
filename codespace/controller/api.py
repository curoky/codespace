"""HTTP routes for the local Codespace control plane."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi import Path as ApiPath

from codespace.controller.models import (
    CreateInstanceRequest,
    DashboardResponse,
    DeleteInstanceResult,
    GitProvider,
    Operation,
    UpdateTokenRequest,
)
from codespace.controller.service import CodespaceService, describe_error

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


@router.post("/api/projects/{project}/instances", status_code=202)
def create_instance(
    project: ResourcePath,
    payload: CreateInstanceRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> Operation:
    service = _service(request)
    try:
        operation = service.queue_create(project, payload.host, payload.instance)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(service.create, project, payload.host, payload.instance)
    return operation


@router.delete("/api/projects/{project}/hosts/{host}/operations/{instance}")
def dismiss_failed_operation(
    project: ResourcePath,
    host: HostPath,
    instance: ResourcePath,
    request: Request,
) -> dict[str, bool]:
    service = _service(request)
    try:
        dismissed = service.dismiss_failed_operation(project, host, instance)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"dismissed": dismissed}


@router.delete("/api/projects/{project}/hosts/{host}/instances/{instance}")
def delete_instance(
    project: ResourcePath,
    host: HostPath,
    instance: ResourcePath,
    request: Request,
    purge: Annotated[bool, Query()] = False,
    force: Annotated[bool, Query()] = False,
) -> DeleteInstanceResult:
    service = _service(request)
    try:
        state = service.delete(project, host, instance, purge=purge, force=force)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=describe_error(exc)) from exc
    return DeleteInstanceResult(
        deleted=force,
        workspace_removed=purge and force,
        state=state,
    )
