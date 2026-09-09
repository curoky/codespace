"""Build the browser-facing Dashboard from live Host inventory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from codespace.config import Config
from codespace.operations import Operation
from codespace.services.models import Service
from codespace.web.models import (
    DashboardResponse,
    DashboardWorkspace,
    HostStatus,
    ProjectHostSummary,
    ProjectSummary,
    ServiceHostStatus,
    ServiceSummary,
)
from codespace.workspaces.models import GitProvider, Workspace


@dataclass(frozen=True, slots=True)
class HostInventory:
    status: HostStatus
    workspaces: list[Workspace]
    services: list[Service]


def build(
    config: Config,
    inventories: Mapping[str, HostInventory],
    operations: list[Operation],
    tokens: dict[GitProvider, bool],
) -> DashboardResponse:
    workspaces = [
        workspace for host_name in config.hosts for workspace in inventories[host_name].workspaces
    ]
    return DashboardResponse(
        hosts=[inventories[host_name].status for host_name in config.hosts],
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
        operations=operations,
        tokens=tokens,
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
