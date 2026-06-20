"""Workspace lifecycle orchestration."""

from __future__ import annotations

from collections.abc import Callable

from podman import PodmanClient
from podman.domain.containers import Container

from codespace.config import Config, ProjectConfig
from codespace.errors import ResourceConflict, ResourceNotFound
from codespace.operations import Operation, OperationStatus, OperationStore
from codespace.runtime import container, host
from codespace.runtime.container import PortSpec, SecretSpec
from codespace.runtime.transport import PodmanTransport
from codespace.workspaces import agent, inventory, provider, ssh
from codespace.workspaces.models import (
    CACHE_MOUNT,
    CHECKOUT_PATH_ENV,
    CLONE_URL_ENV,
    CONTAINER_GID,
    CONTAINER_UID,
    CONTROL_MOUNT,
    ENCRYPTED_ENV,
    LABEL_KIND,
    LABEL_PROJECT,
    LABEL_WORKSPACE,
    OPEN_PATH_ENV,
    SOURCE_TYPE_ENV,
    UPLOAD_MOUNT,
    WORKSPACE_CIPHER_MOUNT,
    WORKSPACE_KEY_SECRET,
    WORKSPACE_KIND,
    WORKSPACE_MOUNT,
    WORKSPACE_SSH_PORT,
    GitProvider,
    ProviderSource,
    RepoGitState,
    Workspace,
    WorkspaceContainerSpec,
    WorkspaceSpec,
    workspace_identity,
)

_AGENT_START_TIMEOUT = 60.0
_AGENT_READY_TIMEOUT = 15 * 60.0

type TokenLookup = Callable[[GitProvider], str]


class WorkspaceManager:
    """Own Workspace operations and lifecycle sequencing."""

    def __init__(
        self,
        config: Config,
        transport: PodmanTransport,
        token: TokenLookup,
        *,
        operations: OperationStore | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self._token = token
        self.operations = operations or OperationStore()

    def inventory(self, host_name: str) -> list[Workspace]:
        return inventory.list_workspaces(self.transport.client(host_name), host_name)

    def queue_create(self, project: str, host_name: str, workspace: str) -> Operation:
        configured = self._project(project, host_name)
        if isinstance(configured.source, ProviderSource):
            self._token(configured.source.type)
        spec = self.config.workspace_spec(project, host_name, workspace)
        return self.operations.create(
            Operation(
                id=spec.identity,
                kind="workspace",
                host=host_name,
                resource=workspace,
                project=project,
                status="queued",
                stage="queued",
            )
        )

    def dismiss_failed(self, project: str, host_name: str, workspace: str) -> bool:
        self._project(project, host_name)
        identity = self.config.workspace_spec(project, host_name, workspace).identity
        return self.operations.dismiss_failed(host_name, identity)

    def create(self, project: str, host_name: str, workspace: str) -> None:
        self._project(project, host_name)
        spec = self.config.workspace_spec(project, host_name, workspace)
        with self.operations.run(spec.host, spec.identity):
            self._create(spec)

    def _create(self, spec: WorkspaceSpec) -> None:
        self._stage(spec, "checking inventory", status="running")
        credentials = (
            (spec.source, self._token(spec.source.type))
            if isinstance(spec.source, ProviderSource)
            else None
        )
        client = self.transport.client(spec.host)
        route = self.transport.ssh_route(spec.host)
        current = inventory.list_workspaces(client, spec.host)
        for existing in current:
            if existing.project == spec.project and existing.workspace == spec.workspace:
                raise ResourceConflict(f"workspace {spec.identity!r} already exists")
            if existing.ssh_host_port == spec.ssh_host_port:
                raise ResourceConflict(
                    f"SSH forwarding port collision on host {spec.host!r}: "
                    f"{spec.identity!r} and {existing.id!r} both map to {spec.ssh_host_port}; "
                    "choose a different workspace name"
                )

        forwarded: dict[str, str] = {}
        names = self.config.hosts[spec.host].forward_environment
        if names:
            self._stage(spec, "reading host environment")
            forwarded = host.read_environment(route, names)

        self._stage(spec, f"pulling image {spec.image}")
        container.pull_image(client, spec.image, spec.platform)

        self._stage(spec, "preparing workspace")
        paths = host.remote_data_paths(route).workspace(spec.project, spec.workspace)
        host.prepare_directories(
            route,
            [
                paths.workspace,
                paths.upload,
                paths.cache,
                paths.control,
            ],
        )
        host.reset_workspace_control(route, paths.control)

        self._stage(spec, "creating container")
        created = _create_workspace_container(client, spec, paths, forwarded)

        self._stage(spec, "waiting for workspace agent")
        agent_client = agent.WorkspaceAgentClient(
            self.transport.forward_socket(spec.host, f"{paths.control}/agent.sock")
        )
        if credentials is not None:
            source, token = credentials
            status = agent_client.wait_for("awaiting-provider", timeout=_AGENT_START_TIMEOUT)
            self._stage(spec, "registering deploy key")
            provider.register(
                source.type,
                token,
                source.repository,
                spec.identity,
                status.public_key,
            )
            self._stage(spec, "authorizing repository checkout")
            host.signal_provider_ready(route, paths.control)

        self._stage(
            spec,
            "preparing open path" if spec.source.type == "empty" else "checking out source",
        )
        agent_client.wait_for("ready", timeout=_AGENT_READY_TIMEOUT)

        self._stage(spec, "probing ssh")
        ssh.probe(spec.to_workspace(created.id, status="running"), route)

    def inspect_deletion(self, project: str, host_name: str, workspace: str) -> RepoGitState:
        """Read repository state without starting or changing the Workspace."""
        self._project(project, host_name)
        running = self._container(project, host_name, workspace)
        actual = inventory.read_workspace(running, host_name)
        if actual.source.type == "empty":
            return RepoGitState(unpushed=False, uncommitted=False, detail=[])
        if actual.status != "running":
            raise ResourceConflict(
                f"container {actual.id!r} is {actual.status}; "
                "repository state cannot be inspected while it is not running"
            )
        route = self.transport.ssh_route(host_name)
        paths = host.remote_data_paths(route).workspace(project, workspace)
        agent_client = agent.WorkspaceAgentClient(
            self.transport.forward_socket(host_name, f"{paths.control}/agent.sock")
        )
        return agent_client.git_state()

    def delete(self, project: str, host_name: str, workspace: str, *, purge: bool) -> None:
        """Execute an explicitly confirmed deletion, even when Git inspection is unavailable."""
        self._project(project, host_name)
        running = self._container(project, host_name, workspace)
        actual = inventory.read_workspace(running, host_name)
        if isinstance(actual.source, ProviderSource):
            provider.revoke(
                actual.source.type,
                self._token(actual.source.type),
                actual.source.repository,
                actual.id,
            )
        if purge:
            client = self.transport.client(host_name)
            route = self.transport.ssh_route(host_name)
            paths = host.remote_data_paths(route).workspace(project, workspace)
            running.stop(timeout=10, ignore=True)
            platform = None if actual.platform == "native" else actual.platform
            container.remove_data_directory(
                client,
                actual.image,
                paths.workspaces_root,
                paths.root,
                platform=platform,
            )
        container.remove_container(running)
        self.transport.close_tcp(host_name, actual.ssh_alias)

    def open_tunnel(self, project: str, host_name: str, workspace: str, port: int) -> int:
        """Forward an explicitly configured Workspace port to local loopback."""
        self._project(project, host_name)
        if port not in self.config.project_tunnel_ports(project):
            raise ResourceNotFound(f"tunnel port {port} is not configured for project {project!r}")
        actual = inventory.read_workspace(self._container(project, host_name, workspace), host_name)
        if actual.status != "running":
            raise ResourceConflict(f"workspace {actual.id!r} is not running ({actual.status})")
        route = self.transport.ssh_route(host_name)
        return self.transport.forward_tcp(
            host_name,
            actual.ssh_alias,
            port=port,
            options=ssh.connection_options(actual, route),
            connection_id=actual.container_id,
        )

    def logs(
        self,
        project: str,
        host_name: str,
        workspace: str,
    ) -> str:
        self._project(project, host_name)
        running = self._container(project, host_name, workspace)
        return container.container_logs(running)

    def _container(self, project: str, host_name: str, workspace: str) -> Container:
        identity = workspace_identity(host_name, project, workspace)
        running = container.find_container(
            self.transport.client(host_name),
            identity,
            labels={
                LABEL_KIND: WORKSPACE_KIND,
                LABEL_PROJECT: project,
                LABEL_WORKSPACE: workspace,
            },
        )
        if running is None:
            raise ResourceNotFound(f"workspace {identity!r} not found")
        return running

    def _project(self, project: str, host_name: str) -> ProjectConfig:
        if project not in self.config.projects:
            raise ResourceNotFound(f"unknown project: {project}")
        configured = self.config.projects[project]
        if host_name not in configured.hosts:
            raise ResourceNotFound(
                f"host {host_name!r} is not configured for project {project!r}; "
                f"allowed: {sorted(configured.hosts)}"
            )
        return configured

    def _stage(
        self,
        spec: WorkspaceSpec,
        stage: str,
        *,
        status: OperationStatus | None = None,
    ) -> None:
        self.operations.update(spec.host, spec.identity, status=status, stage=stage)


def _create_workspace_container(
    client: PodmanClient,
    spec: WorkspaceSpec,
    paths: host.WorkspacePaths,
    forwarded_environment: dict[str, str],
) -> Container:
    environment = {
        **forwarded_environment,
        **spec.container.environment,
        SOURCE_TYPE_ENV: spec.source.type,
        CHECKOUT_PATH_ENV: spec.checkout_path,
        OPEN_PATH_ENV: spec.open_path,
        ENCRYPTED_ENV: str(spec.encrypted).lower(),
    }
    if spec.source.clone_url is not None:
        environment[CLONE_URL_ENV] = spec.source.clone_url

    secrets = list(spec.container.secrets)
    if spec.encrypted:
        secrets.append(
            SecretSpec(
                source=WORKSPACE_KEY_SECRET,
                uid=str(CONTAINER_UID),
                gid=str(CONTAINER_GID),
                mode=0o400,
            )
        )

    mounts: list[dict[str, object]] = [
        {
            "type": "bind",
            "source": paths.workspace,
            "target": WORKSPACE_CIPHER_MOUNT if spec.encrypted else WORKSPACE_MOUNT,
        },
        {"type": "bind", "source": paths.upload, "target": UPLOAD_MOUNT},
        {"type": "bind", "source": paths.cache, "target": CACHE_MOUNT},
        {"type": "bind", "source": paths.control, "target": CONTROL_MOUNT},
    ]
    runtime_spec = WorkspaceContainerSpec.model_validate(
        {
            **spec.container.model_dump(),
            "secrets": secrets,
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
        spec.image,
        name=spec.identity,
        spec=runtime_spec,
        environment=environment,
        labels=spec.labels(),
        mounts=mounts,
        platform=spec.platform,
    )
