"""Read managed Podman environments and deployments from their labels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import NotFound

from controller.config import Config, EnvironmentSpec
from controller.models import (
    LABEL_DEPLOYMENT,
    LABEL_DEPLOYMENT_ID,
    LABEL_GIT_URL,
    LABEL_IMAGE,
    LABEL_INSTANCE,
    LABEL_MANAGED,
    LABEL_PLATFORM,
    LABEL_PROVIDER,
    LABEL_REPO,
    LABEL_SSH_PORT,
    LABEL_TYPE,
    LABEL_WORKSPACE,
    Deployment,
    Environment,
    GitProvider,
    PlatformSelection,
    WorkspaceType,
    deployment_id,
    environment_id,
)


@dataclass(frozen=True, slots=True)
class Inventory:
    environments: list[Environment]
    errors: list[str]


@dataclass(frozen=True, slots=True)
class DeploymentInventory:
    deployments: list[Deployment]
    errors: list[str]


def list_inventory(client: PodmanClient, host: str, config: Config) -> Inventory:
    """Return the managed environments on one host, read straight from labels."""
    containers = client.containers.list(all=True, filters={"label": f"{LABEL_MANAGED}=true"})
    environments = [read_environment(container, host, config) for container in containers]
    environments.sort(key=lambda environment: (environment.workspace, environment.instance))
    return Inventory(environments=environments, errors=[])


def read_environment(container: Container, host: str, config: Config) -> Environment:
    """Build an environment model from one managed container's labels."""
    labels = container.labels or {}
    workspace = labels[LABEL_WORKSPACE]
    instance = labels[LABEL_INSTANCE]
    return Environment(
        id=environment_id(host, workspace, instance),
        host=host,
        workspace=workspace,
        instance=instance,
        type=cast("WorkspaceType", labels[LABEL_TYPE]),
        repo=labels.get(LABEL_REPO),
        provider=cast("GitProvider | None", labels.get(LABEL_PROVIDER)),
        git_url=labels.get(LABEL_GIT_URL),
        image=labels[LABEL_IMAGE],
        platform=cast("PlatformSelection", labels[LABEL_PLATFORM]),
        ssh_port=int(labels[LABEL_SSH_PORT]),
        container_id=container.id,
        status=container_status(container),
    )


def find_container(
    client: PodmanClient,
    spec: EnvironmentSpec,
    config: Config,
) -> Container | None:
    """Find the deterministic container for a resolved instance."""
    try:
        return client.containers.get(spec.identity)
    except NotFound:
        return None


def container_status(container: Container) -> str | None:
    state = container.attrs.get("State")
    if isinstance(state, str):
        return state or None
    if isinstance(state, dict):
        status = state.get("Status")
        return str(status) if status else None
    return None


def list_deployments(client: PodmanClient, host: str, config: Config) -> DeploymentInventory:
    """Return the deployment containers on one host, read straight from labels.

    Filters strictly on ``codespace.deployment=true`` so it never sees managed
    environment containers, and vice versa.
    """
    containers = client.containers.list(all=True, filters={"label": f"{LABEL_DEPLOYMENT}=true"})
    deployments = [read_deployment(container, host, config) for container in containers]
    deployments.sort(key=lambda deployment: deployment.deployment)
    return DeploymentInventory(deployments=deployments, errors=[])


def read_deployment(container: Container, host: str, config: Config) -> Deployment:
    """Build a deployment model from one deployment container's labels."""
    labels = container.labels or {}
    deployment = labels[LABEL_DEPLOYMENT_ID]
    return Deployment(
        id=deployment_id(deployment),
        deployment=deployment,
        host=host,
        image=labels[LABEL_IMAGE],
        container_id=container.id,
        status=container_status(container),
    )


def find_deployment_container(
    client: PodmanClient,
    deployment: str,
    host: str,
    config: Config,
) -> Container | None:
    """Find the deterministic container for a deployment on one host."""
    try:
        return client.containers.get(deployment_id(deployment))
    except NotFound:
        return None
