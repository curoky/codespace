"""Build the browser-facing dashboard from host inventory."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from controller import deployment as deployments_state
from controller.config import Config
from controller.inventory import DeploymentInventory
from controller.models import (
    DashboardEnvironment,
    DashboardResponse,
    DeploymentOperation,
    Environment,
    GitProvider,
    HostStatus,
    Operation,
    WorkspaceSummary,
    WorkspaceSummaryHost,
)


@dataclass(frozen=True, slots=True)
class HostInventory:
    status: HostStatus
    environments: list[Environment]
    deployments: DeploymentInventory | None = None


def build(
    config: Config,
    inventories: Mapping[str, HostInventory],
    operations: list[Operation],
    deployment_operations: list[DeploymentOperation],
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
        workspaces=[
            WorkspaceSummary(
                id=workspace_id,
                hosts=[
                    WorkspaceSummaryHost(name=entry.name, platform=entry.platform)
                    for entry in workspace.host
                ],
                type=workspace.type,
                provider=workspace.provider,
                repo=workspace.repo,
                git_url=workspace.git_url,
                image=config.workspace_image(workspace_id),
                description=workspace.description,
                open_path=config.workspace_open_path(workspace_id),
            )
            for workspace_id, workspace in config.workspaces.items.items()
        ],
        environments=[
            DashboardEnvironment.from_environment(
                environment,
                config.workspace_open_path(environment.workspace),
            )
            for environment in sorted(
                environments,
                key=lambda item: (item.workspace, item.instance),
            )
        ],
        deployments=deployments_state.build_summaries(
            config,
            {host: inventories[host].deployments for host in config.hosts},
            {(op.host, op.deployment): op for op in deployment_operations},
        ),
        operations=operations,
        tokens=tokens,
    )
