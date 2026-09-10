"""Workspace lifecycle orchestration."""

from __future__ import annotations

from collections.abc import Callable

from podman import PodmanClient
from podman.domain.containers import Container

from codespace.config import Config, ProjectConfig
from codespace.operations import Operation, OperationStatus, OperationStore
from codespace.runtime import container, host
from codespace.runtime.container import SecretSpec
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
    HOME_CACHE_MOUNTS,
    LABEL_KIND,
    LABEL_PROJECT,
    LABEL_WORKSPACE,
    OPEN_PATH_ENV,
    SOURCE_TYPE_ENV,
    SSHD_BIND_ENV,
    SSHD_PORT_ENV,
    UPLOAD_MOUNT,
    WORKSPACE_CIPHER_MOUNT,
    WORKSPACE_KEY_SECRET,
    WORKSPACE_KIND,
    WORKSPACE_MOUNT,
    GitProvider,
    ProviderSource,
    RepoGitState,
    Workspace,
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
                raise RuntimeError(f"workspace {spec.identity!r} already exists")
            if existing.ssh_port == spec.ssh_port:
                raise RuntimeError(
                    f"SSH port collision on host {spec.host!r}: "
                    f"{spec.identity!r} and {existing.id!r} both map to {spec.ssh_port}; "
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
                *(source for source, _target in paths.home_cache_mounts(HOME_CACHE_MOUNTS)),
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
            status = agent_client.wait_for({"awaiting-provider"}, timeout=_AGENT_START_TIMEOUT)
            if status.public_key is None:
                raise RuntimeError("deploy key missing for repository source")
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
        agent_client.wait_for({"ready"}, timeout=_AGENT_READY_TIMEOUT)

        self._stage(spec, "probing ssh")
        ssh.probe(spec.to_workspace(created.id, status="running"), route)

        self._stage(spec, "writing ssh config")
        ssh.write_host(
            spec.host,
            inventory.list_workspaces(client, spec.host),
            route,
        )

    def delete(
        self,
        project: str,
        host_name: str,
        workspace: str,
        *,
        purge: bool,
        force: bool = False,
    ) -> RepoGitState:
        self._project(project, host_name)
        client = self.transport.client(host_name)
        route = self.transport.ssh_route(host_name)
        running = self._container(project, host_name, workspace)
        actual = inventory.read_workspace(running, host_name)
        credentials = (
            (actual.source, self._token(actual.source.type))
            if isinstance(actual.source, ProviderSource)
            else None
        )

        if not force:
            if actual.source.type != "empty":
                if actual.status != "running":
                    raise RuntimeError(
                        f"container {actual.id!r} is {actual.status}; "
                        "repository state cannot be inspected while it is not running"
                    )
                paths = host.remote_data_paths(route).workspace(project, workspace)
                agent_client = agent.WorkspaceAgentClient(
                    self.transport.forward_socket(host_name, f"{paths.control}/agent.sock")
                )
                return agent_client.git_state()
            return RepoGitState()

        if credentials is not None:
            source, token = credentials
            provider.revoke(
                source.type,
                token,
                source.repository,
                actual.id,
            )
        if purge:
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
        self.transport.close_tcp(host_name, actual.id)
        ssh.write_host(host_name, inventory.list_workspaces(client, host_name), route)
        return RepoGitState()

    def open_tunnel(self, project: str, host_name: str, workspace: str, port: int) -> int:
        """Forward an explicitly configured Workspace port to local loopback."""
        self._project(project, host_name)
        if port not in self.config.project_tunnel_ports(project):
            raise KeyError(f"tunnel port {port} is not configured for project {project!r}")
        actual = inventory.read_workspace(self._container(project, host_name, workspace), host_name)
        if actual.status != "running":
            raise RuntimeError(f"workspace {actual.id!r} is not running ({actual.status})")
        route = self.transport.ssh_route(host_name)
        return self.transport.forward_tcp(
            host_name,
            actual.id,
            port=port,
            options=ssh.connection_options(actual, route),
            connection_id=actual.container_id,
        )

    def logs(
        self,
        project: str,
        host_name: str,
        workspace: str,
        source: str = container.CONTAINER_LOG_SOURCE,
    ) -> container.LogSnapshot:
        self._project(project, host_name)
        running = self._container(project, host_name, workspace)
        return container.container_log_snapshot(running, source)

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
            raise RuntimeError(f"workspace {identity!r} not found")
        return running

    def _project(self, project: str, host_name: str) -> ProjectConfig:
        try:
            configured = self.config.projects[project]
        except KeyError as exc:
            raise KeyError(f"unknown project: {project}") from exc
        if host_name not in configured.hosts:
            raise KeyError(
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
        **(spec.container.environment or {}),
        SOURCE_TYPE_ENV: spec.source.type,
        CHECKOUT_PATH_ENV: spec.checkout_path,
        OPEN_PATH_ENV: spec.open_path,
        ENCRYPTED_ENV: str(spec.encrypted).lower(),
        SSHD_PORT_ENV: str(spec.ssh_port),
    }
    if spec.source.clone_url is not None:
        environment[CLONE_URL_ENV] = spec.source.clone_url

    runtime_spec = spec.container
    if spec.encrypted:
        secrets = [
            *(runtime_spec.secrets or []),
            SecretSpec(
                source=WORKSPACE_KEY_SECRET,
                uid=str(CONTAINER_UID),
                gid=str(CONTAINER_GID),
                mode=0o400,
            ),
        ]
        runtime_spec = runtime_spec.model_copy(update={"secrets": secrets})

    mounts: list[dict[str, object]] = [
        {
            "type": "bind",
            "source": paths.workspace,
            "target": WORKSPACE_CIPHER_MOUNT if spec.encrypted else WORKSPACE_MOUNT,
        },
        {"type": "bind", "source": paths.upload, "target": UPLOAD_MOUNT},
        {"type": "bind", "source": paths.cache, "target": CACHE_MOUNT},
    ]
    mounts.extend(
        {"type": "bind", "source": source, "target": target}
        for source, target in paths.home_cache_mounts(HOME_CACHE_MOUNTS)
    )
    mounts.append({"type": "bind", "source": paths.control, "target": CONTROL_MOUNT})
    extra_ports: dict[str, object] = {}
    if runtime_spec.is_bridge:
        environment[SSHD_BIND_ENV] = "0.0.0.0"  # noqa: S104
        extra_ports[f"{spec.ssh_port}/tcp"] = ("127.0.0.1", spec.ssh_port)

    return container.create_container(
        client,
        spec.image,
        name=spec.identity,
        spec=runtime_spec,
        environment=environment,
        labels=spec.labels(),
        mounts=mounts,
        platform=spec.platform,
        extra_ports=extra_ports,
    )
