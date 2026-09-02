"""Build the browser-facing Dashboard from live Host inventory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from codespace.config import Config, GitSource, ProviderSource
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
                        platform=placement.platform,
                        image=config.project_image(project_id, host_name),
                    )
                    for host_name, placement in project.hosts.items()
                ],
                source=project.source.type,
                repository=(
                    project.source.repository
                    if isinstance(project.source, ProviderSource)
                    else None
                ),
                git_url=project.source.url if isinstance(project.source, GitSource) else None,
                description=project.description,
                checkout_path=project.resolved_checkout_path(),
                open_path=project.resolved_open_path(),
            )
            for project_id, project in config.projects.items()
        ],
        workspaces=[
            DashboardWorkspace.from_workspace(
                workspace,
                config.projects[workspace.project].resolved_open_path(),
            )
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
    summaries: list[ServiceSummary] = []
    for service_id in config.services:
        hosts: list[ServiceHostStatus] = []
        for host_name in config.service_hosts(service_id):
            host_inventory = inventories[host_name]
            actual = next(
                (item for item in host_inventory.services if item.service == service_id),
                None,
            )
            if host_inventory.status.status == "offline":
                hosts.append(
                    ServiceHostStatus(
                        host=host_name,
                        state="missing",
                        image=config.service_image(service_id, host_name),
                        error="host offline",
                    )
                )
            elif actual is None:
                hosts.append(
                    ServiceHostStatus(
                        host=host_name,
                        state="missing",
                        image=config.service_image(service_id, host_name),
                    )
                )
            else:
                hosts.append(
                    ServiceHostStatus(
                        host=host_name,
                        state="running" if actual.status == "running" else "stopped",
                        image=actual.image,
                        status=actual.status,
                        container_id=actual.container_id,
                    )
                )
        summaries.append(ServiceSummary(id=service_id, hosts=hosts))
    return summaries
