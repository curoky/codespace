"""HTTP routes for the local Codespace control plane."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi import Path as ApiPath

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
    try:
        operation = service.queue_create(workspace, payload.host, payload.instance)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(service.create, workspace, payload.host, payload.instance)
    return operation


@router.delete("/api/workspaces/{workspace}/hosts/{host}/operations/{instance}")
def dismiss_failed_operation(
    workspace: ResourcePath,
    host: HostPath,
    instance: ResourcePath,
    request: Request,
) -> dict[str, bool]:
    service = _service(request)
    try:
        dismissed = service.dismiss_failed_operation(workspace, host, instance)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"dismissed": dismissed}


@router.get("/api/workspaces/{workspace}/hosts/{host}/instances/{instance}/logs")
def instance_logs(
    workspace: ResourcePath,
    host: HostPath,
    instance: ResourcePath,
    request: Request,
) -> ContainerLogsResult:
    service = _service(request)
    try:
        logs = service.logs(workspace, host, instance)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=describe_error(exc)) from exc
    return ContainerLogsResult(logs=logs)


@router.delete("/api/workspaces/{workspace}/hosts/{host}/instances/{instance}")
def delete_instance(
    workspace: ResourcePath,
    host: HostPath,
    instance: ResourcePath,
    request: Request,
    purge: Annotated[bool, Query()] = False,
    force: Annotated[bool, Query()] = False,
) -> DeleteInstanceResult:
    service = _service(request)
    try:
        state = service.delete(workspace, host, instance, purge=purge, force=force)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=describe_error(exc)) from exc
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
    try:
        operation = service.queue_deploy(deployment, host)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(service.deploy, deployment, host)
    return operation


@router.delete("/api/deployments/{deployment}/hosts/{host}")
def clean_deployment(
    deployment: ResourcePath,
    host: HostPath,
    request: Request,
    purge: Annotated[bool, Query()] = False,
) -> DeleteDeploymentResult:
    service = _service(request)
    try:
        removed = service.clean_deployment(deployment, host, purge=purge)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=describe_error(exc)) from exc
    return DeleteDeploymentResult(removed=removed, data_removed=purge)


@router.get("/api/deployments/{deployment}/hosts/{host}/logs")
def deployment_logs(
    deployment: ResourcePath,
    host: HostPath,
    request: Request,
) -> ContainerLogsResult:
    service = _service(request)
    try:
        logs = service.deployment_logs(deployment, host)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=describe_error(exc)) from exc
    return ContainerLogsResult(logs=logs)


@router.delete("/api/deployments/{deployment}/hosts/{host}/operations")
def dismiss_failed_deployment_operation(
    deployment: ResourcePath,
    host: HostPath,
    request: Request,
) -> dict[str, bool]:
    service = _service(request)
    try:
        dismissed = service.dismiss_failed_deployment_operation(deployment, host)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"dismissed": dismissed}
