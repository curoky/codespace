"""Build the browser-facing Dashboard from live Host inventory."""

from __future__ import annotations

from collections.abc import Mapping

from codespace.config import Config
from codespace.control import ControlPlane, HostFailure, HostInventory
from codespace.web.models import (
    DashboardResponse,
    DashboardWorkspace,
    HostStatus,
    ProjectHostSummary,
    ProjectSummary,
    ServiceHostStatus,
    ServiceSummary,
)


def build(control: ControlPlane) -> DashboardResponse:
    config = control.config
    collected = control.inventory()
    inventories = {
        host: result for host, result in collected.items() if isinstance(result, HostInventory)
    }
    workspaces = [
        workspace for inventory in inventories.values() for workspace in inventory.workspaces
    ]
    return DashboardResponse(
        hosts=[
            HostStatus(
                id=result.host, status=result.status, workspace_count=None, error=result.error
            )
            if isinstance(result, HostFailure)
            else HostStatus(
                id=result.host, status="online", workspace_count=len(result.workspaces), error=None
            )
            for result in collected.values()
        ],
        projects=[
            ProjectSummary(
                id=project_id,
                hosts=[
                    ProjectHostSummary(
                        name=host_name,
                        platform=config.project_platform(project_id, host_name),
                        image=config.project_image(project_id, host_name),
                    )
                    for host_name in project.hosts
                ],
                source=project.source,
                description=project.description,
                open_path=project.resolved_open_path(),
                tunnel_ports=config.project_tunnel_ports(project_id),
            )
            for project_id, project in config.projects.items()
        ],
        workspaces=[
            DashboardWorkspace.model_validate(workspace, from_attributes=True)
            for workspace in sorted(
                workspaces,
                key=lambda item: (item.project, item.workspace),
            )
        ],
        services=_service_summaries(config, inventories),
        operations=[*control.workspaces.operations.list(), *control.services.operations.list()],
        tokens=control.tokens.status(),
    )


def _service_summaries(
    config: Config,
    inventories: Mapping[str, HostInventory],
) -> list[ServiceSummary]:
    actual = {
        (service.host, service.service): service
        for inventory in inventories.values()
        for service in inventory.services
    }
    return [
        ServiceSummary(
            id=service_id,
            hosts=[
                ServiceHostStatus(
                    host=host_name,
                    desired_image=config.service_image(service_id, host_name),
                    container=actual.get((host_name, service_id)),
                )
                for host_name in config.service_hosts(service_id)
            ],
        )
        for service_id in config.services
    ]
