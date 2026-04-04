"""Host-level deployment lifecycle orchestration.

A deployment is a self-contained image (sidecar, LLM serving, ...) that a host
opts into via ``hosts.<host>.deployments``. Unlike an environment it has no
workspace, SSH projection or git checkout, so its lifecycle is a plain
"reconcile the deterministic container" plus optional managed-data removal.

These functions layer :mod:`controller.container`, :mod:`controller.inventory`
and :mod:`controller.ssh` primitives into staged deploy/clean/purge sequences.
:class:`controller.service.CodespaceService` owns the transport, the operation
store and the staging callbacks; this module keeps the deployment-specific
sequencing out of that environment-focused orchestrator.
"""

from __future__ import annotations

from collections.abc import Callable

from podman import PodmanClient

from controller import container as containers
from controller import inventory, ssh
from controller.config import Config, DeploymentSpec
from controller.models import (
    DeploymentHostStatus,
    DeploymentOperation,
    DeploymentSummary,
    deployment_id,
)
from controller.runtime.transport import SSHRoute

type Stage = Callable[[str], None]


def reconcile(
    client: PodmanClient,
    route: SSHRoute,
    spec: DeploymentSpec,
    *,
    stage: Stage,
) -> None:
    """Pull, (re)create and start one deployment's deterministic container.

    Replacing is safe because a deployment owns its deterministic name; the
    previous container is force-removed before the new one is created so a
    repeated deploy always converges to the configured image and container block.
    """
    stage(f"pulling image {spec.image}")
    containers.pull_image(client, spec.image, None)

    stage("preparing data root")
    data_root = ssh.remote_deployment_root(route)
    ssh.prepare_instance_dirs(route, [spec.data_path(data_root)])

    stage("replacing container")
    if client.containers.exists(spec.identity):
        client.containers.get(spec.identity).remove(force=True)

    stage("creating container")
    containers.create_deployment_container(client, spec, data_root)


def teardown(
    client: PodmanClient,
    route: SSHRoute,
    spec: DeploymentSpec,
    config: Config,
    *,
    purge: bool,
    stage: Stage,
) -> bool:
    """Remove one deployment's container and, when ``purge``, its managed data.

    Returns whether a container was found and removed. Purging removes the
    ``~/codespace-deployment/<id>`` data directory after the container is gone.
    """
    stage("removing container")
    container = inventory.find_deployment_container(
        client,
        spec.deployment_id,
        spec.host,
        config,
    )
    removed = container is not None
    if container is not None:
        containers.remove_container(container)

    if purge:
        stage("removing data")
        data_root = ssh.remote_deployment_root(route)
        containers.remove_workspace(
            client,
            spec.image,
            data_root,
            spec.data_path(data_root),
        )
    return removed


def build_summaries(
    config: Config,
    inventories: dict[str, inventory.DeploymentInventory | None],
    operations: dict[tuple[str, str], DeploymentOperation],
) -> list[DeploymentSummary]:
    """Project the deployment catalog with each declared host's actual state.

    ``inventories`` maps host to its deployment inventory, or ``None`` when the
    host is offline. Each catalog entry lists only the hosts that declared it,
    joining live container state with any in-flight operation for that host.
    """
    summaries: list[DeploymentSummary] = []
    for deployment_name, deployment in config.deployments.items():
        hosts = [
            _host_status(
                host,
                deployment_name,
                inventories.get(host),
                operations.get((host, deployment_name)),
            )
            for host in config.deployment_hosts(deployment_name)
        ]
        summaries.append(
            DeploymentSummary(
                id=deployment_name,
                image=deployment.image,
                description=deployment.description,
                hosts=hosts,
            )
        )
    return summaries


def _host_status(
    host: str,
    deployment_name: str,
    host_inventory: inventory.DeploymentInventory | None,
    operation: DeploymentOperation | None,
) -> DeploymentHostStatus:
    if host_inventory is None:
        return DeploymentHostStatus(
            host=host,
            state="missing",
            error="host offline",
            operation=operation,
        )
    identity = deployment_id(deployment_name)
    found = next((item for item in host_inventory.deployments if item.id == identity), None)
    if found is None:
        return DeploymentHostStatus(host=host, state="missing", operation=operation)
    return DeploymentHostStatus(
        host=host,
        state="running" if found.status == "running" else "stopped",
        status=found.status,
        container_id=found.container_id,
        operation=operation,
    )
