"""Read Workspace containers from the canonical Podman labels."""

from __future__ import annotations

from typing import cast

from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import NotFound

from codespace.workspaces.models import (
    LABEL_GIT_URL,
    LABEL_IMAGE,
    LABEL_KIND,
    LABEL_PLATFORM,
    LABEL_PROJECT,
    LABEL_REPOSITORY,
    LABEL_SOURCE,
    LABEL_SSH_PORT,
    LABEL_WORKSPACE,
    WORKSPACE_KIND,
    PlatformSelection,
    SourceType,
    Workspace,
    WorkspaceSpec,
    workspace_identity,
)


def list_workspaces(client: PodmanClient, host: str) -> list[Workspace]:
    containers = client.containers.list(
        all=True,
        filters={"label": f"{LABEL_KIND}={WORKSPACE_KIND}"},
    )
    workspaces = [read_workspace(container, host) for container in containers]
    workspaces.sort(key=lambda item: (item.project, item.workspace))
    return workspaces


def read_workspace(container: Container, host: str) -> Workspace:
    labels = container.labels or {}
    project = labels[LABEL_PROJECT]
    workspace = labels[LABEL_WORKSPACE]
    return Workspace(
        id=workspace_identity(host, project, workspace),
        project=project,
        workspace=workspace,
        host=host,
        source=cast("SourceType", labels[LABEL_SOURCE]),
        repository=labels.get(LABEL_REPOSITORY),
        git_url=labels.get(LABEL_GIT_URL),
        image=labels[LABEL_IMAGE],
        platform=cast("PlatformSelection", labels[LABEL_PLATFORM]),
        ssh_port=int(labels[LABEL_SSH_PORT]),
        container_id=container.id,
        status=container_status(container),
    )


def find_container(client: PodmanClient, spec: WorkspaceSpec) -> Container | None:
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
