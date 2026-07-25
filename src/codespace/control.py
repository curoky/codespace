"""Host inventory and the shared Service / Workspace lifecycle."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Literal

from podman.domain.containers import Container

from codespace import services, workspaces
from codespace.config import Config
from codespace.operations import Operation, OperationStore, describe_error
from codespace.resources import Resource, ResourceConflict, ResourceNotFound
from codespace.runtime import container, host
from codespace.runtime.transport import PodmanTransport, TransportError
from codespace.services import Service, ServiceSpec
from codespace.workspaces import (
    GitProvider,
    ProviderSource,
    RepoGitState,
    Workspace,
    WorkspaceSpec,
    provider,
    ssh,
)
from codespace.workspaces import lifecycle as workspace_runtime


@dataclass(frozen=True, slots=True)
class HostInventory:
    host: str
    workspaces: list[Workspace]
    services: list[Service]


@dataclass(frozen=True, slots=True)
class HostFailure:
    host: str
    status: Literal["offline", "error"]
    error: str


class ControlPlane:
    """Own connections, resource operations, and process-local tokens."""

    def __init__(
        self,
        config: Config,
        *,
        transport: PodmanTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or PodmanTransport(config.hosts)
        self.operations = OperationStore()
        self._tokens = config.seed_tokens()
        self._token_lock = Lock()

    def set_token(self, provider: GitProvider, token: str) -> None:
        with self._token_lock:
            self._tokens[provider] = token

    def _token(self, provider: GitProvider) -> str:
        with self._token_lock:
            token = self._tokens.get(provider)
        if token is None:
            raise ResourceConflict(f"{provider} token is not set")
        return token

    def token_status(self) -> dict[GitProvider, bool]:
        with self._token_lock:
            return {"github": "github" in self._tokens, "gitlab": "gitlab" in self._tokens}

    def close(self) -> None:
        self.transport.close()

    def inventory(self) -> dict[str, HostInventory | HostFailure]:
        with ThreadPoolExecutor(max_workers=len(self.config.hosts)) as executor:
            return dict(
                zip(
                    self.config.hosts,
                    executor.map(self._host_inventory, self.config.hosts),
                    strict=True,
                )
            )

    def _host_inventory(self, host_name: str) -> HostInventory | HostFailure:
        try:
            client = self.transport.client(host_name)
            return HostInventory(
                host=host_name,
                workspaces=workspaces.list_workspaces(client, host_name),
                services=services.list_services(client, host_name),
            )
        except Exception as exc:
            return HostFailure(
                host=host_name,
                status="offline" if isinstance(exc, TransportError) else "error",
                error=describe_error(exc),
            )

    def queue(self, resource: Resource) -> Operation:
        spec = self.config.resource_spec(resource)
        if isinstance(spec, WorkspaceSpec) and isinstance(spec.source, ProviderSource):
            self._token(spec.source.type)
        return self.operations.create(
            Operation(
                id=resource.id,
                kind=resource.kind,
                host=resource.host,
                resource=resource.name,
                project=resource.project,
                status="queued",
                stage="queued",
            )
        )

    def dismiss_failed(self, resource: Resource) -> bool:
        self.config.resource_spec(resource)
        return self.operations.dismiss_failed(resource.host, resource.id)

    def deploy(self, resource: Resource) -> None:
        spec = self.config.resource_spec(resource)
        with self.operations.run(resource.host, resource.id):
            self._deploy(resource, spec)

    def _deploy(self, resource: Resource, spec: WorkspaceSpec | ServiceSpec) -> None:
        def stage(message: str) -> None:
            self.operations.update(resource.host, resource.id, status="running", stage=message)

        stage("checking inventory")
        credentials = (
            (spec.source, self._token(spec.source.type))
            if isinstance(spec, WorkspaceSpec) and isinstance(spec.source, ProviderSource)
            else None
        )
        client = self.transport.client(resource.host)
        route = self.transport.ssh_route(resource.host)
        existing = None
        forwarded: dict[str, str] = {}
        if isinstance(spec, WorkspaceSpec):
            workspace_runtime.check_inventory(client, spec)
            names = self.config.hosts[resource.host].forward_environment
            if names:
                stage("reading host environment")
                forwarded = host.read_environment(route, names)
        else:
            existing = container.find_container(
                client, resource.container_name, labels=resource.labels
            )

        stage(f"pulling image {spec.image}")
        platform = spec.platform if isinstance(spec, WorkspaceSpec) else None
        container.pull_image(client, spec.image, platform)
        data = host.remote_data_paths(route)
        if isinstance(spec, WorkspaceSpec):
            stage("preparing workspace")
            paths = data.workspace(spec.project, spec.workspace)
            host.prepare_directories(
                route, [paths.workspace, paths.upload, paths.cache, paths.control]
            )
            host.reset_workspace_control(route, paths.control)
            stage("creating container")
            created = workspace_runtime.create_container(client, spec, paths, forwarded)
            workspace_runtime.bootstrap(spec, created, self.transport, paths, credentials, stage)
        else:
            stage("preparing data root")
            path = data.service(spec.service)
            host.prepare_directories(route, [path])
            stage("replacing container")
            if existing is not None:
                container.remove_container(existing)
            stage("creating container")
            container.create_container(
                client,
                spec.image,
                name=resource.container_name,
                spec=spec.resolve_data_path(path),
                environment=spec.container.environment,
                labels=spec.labels(),
                mounts=[],
                restart_policy={"Name": "unless-stopped"},
            )

    def inspect_deletion(self, resource: Resource) -> RepoGitState:
        actual = workspaces.read_workspace(self._container(resource), resource.host)
        return workspace_runtime.inspect_deletion(actual, self.transport)

    def remove(self, resource: Resource, *, purge: bool = False) -> bool:
        spec = self.config.resource_spec(resource)
        client = self.transport.client(resource.host)
        running = container.find_container(client, resource.container_name, labels=resource.labels)
        if resource.project is None:
            if running is not None:
                container.remove_container(running)
            if purge:
                data = host.remote_data_paths(self.transport.ssh_route(resource.host))
                container.remove_data_directory(
                    client, spec.image, data.services, data.service(resource.name)
                )
            return running is not None
        if running is None:
            raise ResourceNotFound(
                f"workspace container {resource.container_name!r} "
                f"not found on host {resource.host!r}"
            )
        actual = workspaces.read_workspace(running, resource.host)
        if isinstance(actual.source, ProviderSource):
            provider.revoke(
                actual.source.type,
                self._token(actual.source.type),
                actual.source.repository,
                actual.id,
            )
        if purge:
            paths = host.remote_data_paths(self.transport.ssh_route(resource.host)).workspace(
                resource.project, resource.name
            )
            running.stop(timeout=10, ignore=True)
            container.remove_data_directory(
                client,
                actual.image,
                paths.workspaces_root,
                paths.root,
                platform=None if actual.platform == "native" else actual.platform,
            )
        container.remove_container(running)
        self.transport.close_tcp(resource.host, actual.ssh_alias)
        ssh.remove_route(actual)
        return True

    def logs(self, resource: Resource) -> str:
        return container.container_logs(self._container(resource))

    def open_tunnel(self, resource: Resource, port: int) -> int:
        self.config.resource_spec(resource)
        ports = (
            self.config.project_tunnel_ports(resource.project)
            if resource.project is not None
            else self.config.service_tunnel_ports(resource.name, resource.host)
        )
        if port not in ports:
            raise ResourceNotFound(
                f"tunnel port {port} is not configured for {resource.kind} {resource.id!r}"
            )
        running = self._container(resource)
        actual = (
            workspaces.read_workspace(running, resource.host)
            if resource.project is not None
            else services.read_service(running, resource.host)
        )
        if actual.status != "running":
            raise ResourceConflict(
                f"{resource.kind} {actual.id!r} is not running ({actual.status})"
            )
        route = self.transport.ssh_route(resource.host)
        if isinstance(actual, Workspace):
            return self.transport.forward_tcp(
                resource.host,
                actual.ssh_alias,
                port=port,
                options=ssh.connection_options(actual, route),
                connection_id=actual.container_id,
            )
        return self.transport.forward_tcp(
            resource.host,
            route.host,
            port=port,
            local_port=port,
            options=[],
            connection_id=actual.container_id,
        )

    def _container(self, resource: Resource) -> Container:
        self.config.resource_spec(resource)
        found = container.find_container(
            self.transport.client(resource.host),
            resource.container_name,
            labels=resource.labels,
        )
        if found is None:
            raise ResourceNotFound(
                f"{resource.kind} container {resource.container_name!r} "
                f"not found on host {resource.host!r}"
            )
        return found
