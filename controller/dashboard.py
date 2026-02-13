"""Build the browser-facing dashboard from host inventory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from controller.config import Config
from controller.models import (
    DashboardEnvironment,
    DashboardResponse,
    Environment,
    GitProvider,
    HostStatus,
    Operation,
    ProjectSummary,
    ProjectSummaryHost,
)


@dataclass(frozen=True, slots=True)
class HostInventory:
    status: HostStatus
    environments: list[Environment]


def build(
    config: Config,
    inventories: Mapping[str, HostInventory],
    operations: list[Operation],
    tokens: dict[GitProvider, bool],
) -> DashboardResponse:
    hosts: list[HostStatus] = []
    environments: list[Environment] = []
    for host in config.hosts:
        result = inventories[host]
        hosts.append(result.status)
        environments.extend(result.environments)

    return DashboardResponse(
        hosts=hosts,
        projects=[
            ProjectSummary(
                id=project_id,
                hosts=[
                    ProjectSummaryHost(name=entry.name, platform=entry.platform)
                    for entry in project.host
                ],
                type=project.type,
                provider=project.provider,
                repo=project.repo,
                image=config.project_image(project_id),
                description=project.description,
                open_path=config.project_open_path(project_id),
            )
            for project_id, project in config.projects.items()
        ],
        environments=[
            DashboardEnvironment.from_environment(
                environment,
                config.project_open_path(environment.project),
            )
            for environment in sorted(
                environments,
                key=lambda item: (item.project, item.instance),
            )
        ],
        operations=operations,
        tokens=tokens,
    )
