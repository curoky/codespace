"""Read Workspace containers from the canonical Podman labels."""

from __future__ import annotations

from typing import cast

from podman import PodmanClient
from podman.domain.containers import Container
from pydantic import TypeAdapter

from codespace.runtime.container import container_status
from codespace.workspaces.models import (
    LABEL_ENCRYPTED,
    LABEL_GIT_URL,
    LABEL_IMAGE,
    LABEL_KIND,
    LABEL_OPEN_PATH,
    LABEL_PLATFORM,
    LABEL_PROJECT,
    LABEL_REPOSITORY,
    LABEL_SOURCE,
    LABEL_SSH_PORT,
    LABEL_WORKSPACE,
    WORKSPACE_KIND,
    PlatformSelection,
    Source,
    Workspace,
    workspace_identity,
)

_SOURCE: TypeAdapter[Source] = TypeAdapter(Source)


def list_workspaces(client: PodmanClient, host: str) -> list[Workspace]:
    containers = client.containers.list(
        all=True,
        filters={"label": f"{LABEL_KIND}={WORKSPACE_KIND}"},
    )
    workspaces = [read_workspace(container, host) for container in containers]
    workspaces.sort(key=lambda item: (item.project, item.workspace))
    return workspaces


def read_workspace(container: Container, host: str) -> Workspace:
    labels = container.labels
    project = labels[LABEL_PROJECT]
    workspace = labels[LABEL_WORKSPACE]
    source = {"type": labels[LABEL_SOURCE]}
    for field, label in (("repository", LABEL_REPOSITORY), ("url", LABEL_GIT_URL)):
        if label in labels:
            source[field] = labels[label]
    return Workspace(
        id=workspace_identity(host, project, workspace),
        project=project,
        workspace=workspace,
        host=host,
        source=_SOURCE.validate_python(source),
        image=labels[LABEL_IMAGE],
        platform=cast("PlatformSelection", labels[LABEL_PLATFORM]),
        ssh_port=int(labels[LABEL_SSH_PORT]),
        open_path=labels[LABEL_OPEN_PATH],
        encrypted={"true": True, "false": False}[labels[LABEL_ENCRYPTED]],
        container_id=container.id,
        status=container_status(container),
    )
