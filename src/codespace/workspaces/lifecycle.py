"""Workspace lifecycle orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from loguru import logger
from podman import PodmanClient
from podman.domain.containers import Container

from codespace.config import Config, ProjectConfig, ProviderSource
from codespace.operations import Operation, OperationStatus, OperationStore, describe_error
from codespace.runtime import container, host
from codespace.runtime.container import SecretSpec
from codespace.runtime.transport import PodmanTransport, SSHRoute
from codespace.workspaces import agent, inventory, provider, ssh
from codespace.workspaces.models import (
    CACHE_MOUNT,
    CHECKOUT_PATH_ENV,
    CLONE_URL_ENV,
    CONTAINER_GID,
    CONTAINER_UID,
    CONTROL_MOUNT,
    HOME_CACHE_MOUNTS,
    OPEN_PATH_ENV,
    SOURCE_TYPE_ENV,
    SSHD_BIND_ENV,
    SSHD_PORT_ENV,
    UPLOAD_MOUNT,
    WORKSPACE_CIPHER_MOUNT,
    WORKSPACE_KEY_ENV,
    WORKSPACE_KEY_SECRET,
    WORKSPACE_MOUNT,
    GitProvider,
    RepoGitState,
    Workspace,
    WorkspaceSpec,
)

_AGENT_START_TIMEOUT = 60.0
_AGENT_READY_TIMEOUT = 15 * 60.0

type TokenLookup = Callable[[GitProvider], str]


@dataclass(slots=True)
class _Creation:
    spec: WorkspaceSpec
    token: str | None = None
    client: PodmanClient | None = None
    route: SSHRoute | None = None


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
        creation = _Creation(spec=self.config.workspace_spec(project, host_name, workspace))
        self._run_operation(creation.spec, lambda: self._create(creation))

    def _create(self, creation: _Creation) -> None:
        spec = creation.spec
        self._stage(spec, "checking inventory", status="running")
        if spec.source in {"github", "gitlab"}:
            creation.token = self._token(cast("GitProvider", spec.source))
        creation.client = self.transport.client(spec.host)
        creation.route = self.transport.ssh_route(spec.host)
        current = inventory.list_workspaces(creation.client, spec.host)
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
            forwarded = host.read_environment(creation.route, names)

        self._stage(spec, f"pulling image {spec.image}")
        container.pull_image(creation.client, spec.image, spec.platform)

        self._stage(spec, "preparing workspace")
        paths = host.remote_data_paths(creation.route).workspace(spec.project, spec.workspace)
        host.prepare_directories(
            creation.route,
            [
                paths.workspace,
                paths.upload,
                paths.cache,
                *(source for source, _target in paths.home_cache_mounts(HOME_CACHE_MOUNTS)),
                paths.control,
            ],
        )
        host.reset_workspace_control(creation.route, paths.control)

        self._stage(spec, "creating container")
        created = _create_workspace_container(creation.client, spec, paths, forwarded)

        self._stage(spec, "waiting for workspace agent")
        agent_client = agent.WorkspaceAgentClient(
            self.transport.forward_socket(spec.host, f"{paths.control}/agent.sock")
        )
        if spec.source in {"github", "gitlab"}:
            status = agent_client.wait_for({"awaiting-provider"}, timeout=_AGENT_START_TIMEOUT)
            if status.public_key is None:
                raise RuntimeError("deploy key missing for repository source")
            if creation.token is None or spec.repository is None:
                raise RuntimeError("provider credentials are incomplete")
            self._stage(spec, "registering deploy key")
            provider.register(
                cast("GitProvider", spec.source),
                creation.token,
                spec.repository,
                spec.identity,
                status.public_key,
            )
            self._stage(spec, "authorizing repository checkout")
            host.signal_provider_ready(creation.route, paths.control)

        self._stage(
            spec,
            "preparing open path" if spec.source == "empty" else "checking out source",
        )
        agent_client.wait_for({"ready"}, timeout=_AGENT_READY_TIMEOUT)

        self._stage(spec, "probing ssh")
        ssh.probe(spec.to_workspace(created.id, status="running"), creation.route)

        self._stage(spec, "writing ssh config")
        ssh.write_host(
            spec.host,
            inventory.list_workspaces(creation.client, spec.host),
            creation.route,
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
        configured = self._project(project, host_name)
        spec = self.config.workspace_spec(project, host_name, workspace)
        token = (
            self._token(configured.source.type)
            if isinstance(configured.source, ProviderSource)
            else None
        )
        client = self.transport.client(host_name)
        route = self.transport.ssh_route(host_name)
        current = inventory.list_workspaces(client, host_name)
        actual = next(
            (item for item in current if item.project == project and item.workspace == workspace),
            None,
        )
        if actual is None:
            raise RuntimeError(f"workspace {spec.identity!r} not found")
        running = inventory.find_container(client, spec)
        if running is None:
            raise RuntimeError(f"workspace {spec.identity!r} not found")

        if not force:
            if spec.source != "empty":
                if actual.status != "running":
                    status = actual.status or "unknown"
                    raise RuntimeError(
                        f"container {spec.identity!r} is {status}; "
                        "repository state cannot be inspected while it is not running"
                    )
                paths = host.remote_data_paths(route).workspace(project, workspace)
                agent_client = agent.WorkspaceAgentClient(
                    self.transport.forward_socket(host_name, f"{paths.control}/agent.sock")
                )
                return agent_client.git_state()
            return RepoGitState()

        if isinstance(configured.source, ProviderSource):
            if token is None:
                raise RuntimeError(f"{configured.source.type} token is not set")
            provider.revoke(
                configured.source.type,
                token,
                configured.source.repository,
                spec.identity,
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
        ssh.write_host(host_name, inventory.list_workspaces(client, host_name), route)
        return RepoGitState()

    def logs(self, project: str, host_name: str, workspace: str) -> str:
        self._project(project, host_name)
        spec = self.config.workspace_spec(project, host_name, workspace)
        running = inventory.find_container(self.transport.client(host_name), spec)
        if running is None:
            raise RuntimeError(f"workspace {spec.identity!r} not found")
        return container.container_logs(running)

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

    def _run_operation(self, spec: WorkspaceSpec, work: Callable[[], object]) -> None:
        try:
            work()
        except Exception as exc:
            logger.exception("failed Workspace operation {} on Host {}", spec.identity, spec.host)
            self.operations.update(
                spec.host,
                spec.identity,
                status="failed",
                stage="failed",
                error=describe_error(exc),
            )
            return
        self.operations.remove(spec.host, spec.identity)

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
        SOURCE_TYPE_ENV: spec.source,
        CHECKOUT_PATH_ENV: spec.checkout_path,
        OPEN_PATH_ENV: spec.open_path,
        SSHD_PORT_ENV: str(spec.ssh_port),
    }
    if spec.clone_url is not None:
        environment[CLONE_URL_ENV] = spec.clone_url

    runtime_spec = spec.container
    if spec.encrypted:
        secrets = dict(runtime_spec.secrets or {})
        secrets["workspace-key"] = SecretSpec(
            source=WORKSPACE_KEY_SECRET,
            mode="env",
            target=WORKSPACE_KEY_ENV,
        )
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
        secret_uid=CONTAINER_UID,
        secret_gid=CONTAINER_GID,
    )
