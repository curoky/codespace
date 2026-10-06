"""Workspace bootstrap and repository inspection around the container lifecycle."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import cast

from podman import PodmanClient
from podman.domain.containers import Container

from codespace.resources import ResourceConflict
from codespace.runtime import container
from codespace.runtime.container import ContainerSpec, PortSpec
from codespace.runtime.transport import PodmanTransport
from codespace.workspaces import (
    CONTROL_MOUNT,
    WORKSPACE_SSH_PORT,
    ProviderSource,
    RepoGitState,
    Workspace,
    WorkspaceSpec,
    agent,
    list_workspaces,
    provider,
    ssh,
)

_AGENT_START_TIMEOUT = 60.0
_AGENT_READY_TIMEOUT = 15 * 60.0


def check_inventory(client: PodmanClient, spec: WorkspaceSpec) -> None:
    for existing in list_workspaces(client, spec.host):
        if existing.project == spec.project and existing.workspace == spec.workspace:
            raise ResourceConflict(f"workspace {spec.id!r} already exists")
        if existing.container_name == spec.container_name:
            raise ResourceConflict(
                f"container name collision on host {spec.host!r}: "
                f"{spec.id!r} and {existing.id!r} both use {spec.container_name!r}"
            )
        if existing.ssh_host_port == spec.ssh_host_port:
            raise ResourceConflict(
                f"SSH forwarding port collision on host {spec.host!r}: "
                f"{spec.id!r} and {existing.id!r} both map to {spec.ssh_host_port}; "
                "choose a different workspace name"
            )


def check_rebuild(actual: Workspace, spec: WorkspaceSpec) -> None:
    actual_source = [source.model_dump(exclude={"args"}) for source in actual.source]
    desired_source = [source.model_dump(exclude={"args"}) for source in spec.source]
    if actual_source != desired_source:
        raise ResourceConflict(
            f"workspace {actual.id!r} source changed; delete and recreate it instead"
        )
    if actual.encrypted != spec.encrypted:
        raise ResourceConflict(
            f"workspace {actual.id!r} encryption changed; delete and recreate it instead"
        )


def bootstrap(
    spec: WorkspaceSpec,
    created: Container,
    transport: PodmanTransport,
    data_path: str,
    credentials: list[tuple[ProviderSource, str]],
    stage: Callable[[str], None],
) -> None:
    provider_sources = [source for source in spec.source if isinstance(source, ProviderSource)]
    if len(credentials) != len(provider_sources):
        raise RuntimeError(f"provider credentials are required to bootstrap {spec.id!r}")
    stage("waiting for workspace agent")
    control_source = next(
        volume.source
        for volume in spec.container.resolve_data_path(data_path).volumes
        if volume.target == CONTROL_MOUNT
    )
    agent_client = agent.WorkspaceAgentClient(
        transport.forward_socket(spec.host, f"{control_source}/agent.sock")
    )
    if credentials:
        status = agent_client.wait_for("awaiting-provider", timeout=_AGENT_START_TIMEOUT)
        stage("registering deploy keys")
        for source, token in credentials:
            provider.register(source.type, token, source.repository, spec.id, status.public_key)
        stage("authorizing repository checkouts")
        agent_client.authorize_provider()
    stage("checking out sources" if spec.source else "preparing open path")
    agent_client.wait_for("ready", timeout=_AGENT_READY_TIMEOUT)
    stage("writing ssh config")
    ssh.write_route(
        spec.to_workspace(
            cast("str", created.id),
            container.container_image_id(created),
            status="running",
        )
    )


def inspect_deletion(
    actual: Workspace, transport: PodmanTransport, running: Container
) -> RepoGitState:
    """Read repository state without starting or changing the Workspace."""
    if not actual.source:
        return RepoGitState(unpushed=False, uncommitted=False, detail=[])
    if actual.status != "running":
        raise ResourceConflict(
            f"container {actual.id!r} is {actual.status}; "
            "repository state cannot be inspected while it is not running"
        )
    control_source = next(
        mount["Source"]
        for mount in running.attrs["Mounts"]
        if mount["Destination"] == CONTROL_MOUNT
    )
    return agent.WorkspaceAgentClient(
        transport.forward_socket(actual.host, f"{control_source}/agent.sock")
    ).git_state()


def create_container(
    client: PodmanClient,
    spec: WorkspaceSpec,
    data_path: str,
    forwarded_environment: dict[str, str],
) -> Container:
    environment = {
        **forwarded_environment,
        **spec.container.environment,
        "CODESPACE_SOURCES": json.dumps(
            [
                {
                    "type": source.type,
                    "clone_url": source.clone_url,
                    "checkout_path": source.resolved_checkout_path(),
                    "args": source.args,
                }
                for source in spec.source
            ]
        ),
        "CODESPACE_OPEN_PATH": spec.open_path,
        "CODESPACE_ENCRYPTED": str(spec.encrypted).lower(),
    }

    runtime_spec = ContainerSpec.model_validate(
        {
            **spec.container.resolve_data_path(data_path).model_dump(),
            "environment": environment,
            "ports": [
                *spec.container.ports,
                PortSpec(
                    target=WORKSPACE_SSH_PORT,
                    published=spec.ssh_host_port,
                    host_ip="127.0.0.1",
                ),
            ],
        }
    )
    return container.create_container(
        client,
        name=spec.container_name,
        spec=runtime_spec,
        labels=spec.labels(),
    )
