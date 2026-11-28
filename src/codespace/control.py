"""Host inventory and the shared Service / Workspace lifecycle."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from loguru import logger
from podman import PodmanClient
from podman.domain.containers import Container

from codespace import services, workspaces
from codespace.config import Config
from codespace.credentials import load_tokens
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
    image_checks: list[WorkspaceImageCheck] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class HostFailure:
    host: str
    status: Literal["offline", "error"]
    error: str


@dataclass(frozen=True, slots=True)
class WorkspaceImageCheck:
    host: str
    image: str
    platform: workspaces.PlatformSelection
    latest_image_id: str | None
    checked_at: datetime
    error: str | None

    @property
    def key(self) -> tuple[str, str, workspaces.PlatformSelection]:
        return self.host, self.image, self.platform


class ControlPlane:
    """Own connections, resource operations, and process-local tokens."""

    def __init__(
        self,
        config: Config,
        *,
        transport: PodmanTransport | None = None,
    ) -> None:
        self._tokens = load_tokens()
        self.config = config
        self.transport = transport or PodmanTransport(config.hosts)
        self.operations = OperationStore()

    def _token(self, provider: GitProvider) -> str:
        return self._tokens[provider]

    def token_status(self) -> dict[GitProvider, bool]:
        return {"github": "github" in self._tokens, "gitlab": "gitlab" in self._tokens}

    def _provider_credentials(
        self, sources: list[workspaces.Source]
    ) -> list[tuple[ProviderSource, str]]:
        return [
            (source, self._token(source.type))
            for source in sources
            if isinstance(source, ProviderSource)
        ]

    @staticmethod
    def _workspace_image_checks(
        client: PodmanClient,
        host_name: str,
        actual: list[Workspace],
    ) -> list[WorkspaceImageCheck]:
        targets: set[tuple[str, workspaces.PlatformSelection]] = {
            (workspace.image, workspace.platform)
            for workspace in actual
            if workspace.status == "running"
        }
        checks: list[WorkspaceImageCheck] = []
        for image, platform in sorted(targets):
            try:
                latest_image_id = container.local_image_id(client, image)
                error = None
            except Exception as exc:
                latest_image_id = None
                error = describe_error(exc)
            checked_at = datetime.now(UTC)
            checks.append(
                WorkspaceImageCheck(
                    host=host_name,
                    image=image,
                    platform=platform,
                    latest_image_id=latest_image_id,
                    checked_at=checked_at,
                    error=error,
                )
            )
        return checks

    def close(self) -> None:
        self.transport.close()

    def inventory(self) -> dict[str, HostInventory | HostFailure]:
        with ThreadPoolExecutor() as executor:
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
            actual_workspaces = workspaces.list_workspaces(client, host_name)
            for workspace in actual_workspaces:
                ssh.write_route(workspace)
            return HostInventory(
                host=host_name,
                workspaces=actual_workspaces,
                services=services.list_services(client, host_name),
                image_checks=self._workspace_image_checks(client, host_name, actual_workspaces),
            )
        except Exception as exc:
            return HostFailure(
                host=host_name,
                status="offline" if isinstance(exc, TransportError) else "error",
                error=describe_error(exc),
            )

    def queue(self, resource: Resource) -> Operation:
        spec = self.config.resource_spec(resource)
        if isinstance(spec, WorkspaceSpec):
            self._provider_credentials(spec.source)
        return self._queue(resource)

    def queue_rebuild(self, resource: Resource) -> Operation:
        spec = self.config.resource_spec(resource)
        if not isinstance(spec, WorkspaceSpec):
            raise ResourceNotFound(f"resource {resource.id!r} is not a workspace")
        self._provider_credentials(spec.source)
        return self._queue(resource)

    def _queue(self, resource: Resource) -> Operation:
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
            self._provider_credentials(spec.source) if isinstance(spec, WorkspaceSpec) else []
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

        data = host.remote_data_paths(route)
        path = (
            data.workspace(spec.project, spec.workspace)
            if isinstance(spec, WorkspaceSpec)
            else data.service(spec.service)
        )
        runtime_spec = (
            workspace_runtime.container_spec(spec, path, forwarded)
            if isinstance(spec, WorkspaceSpec)
            else spec.container.resolve_data_path(path)
        )
        stage("checking secrets")
        runtime_spec.require_secrets(client)
        stage(f"pulling image {spec.image}")
        container.pull_image(
            client,
            runtime_spec.image,
            runtime_spec.platform,
            runtime_spec.pull_policy,
        )
        stage("preparing data root")
        directories = list(dict.fromkeys([path, *runtime_spec.data_directories(path)]))
        host.prepare_directories(route, directories)
        if isinstance(spec, WorkspaceSpec):
            stage("creating container")
            created = container.create_container(
                client, name=resource.container_name, spec=runtime_spec, labels=spec.labels()
            )
            workspace_runtime.bootstrap(spec, created, self.transport, path, credentials, stage)
        else:
            stage("replacing container")
            if existing is not None:
                container.remove_container(existing)
            stage("creating container")
            container.create_container(
                client,
                name=resource.container_name,
                spec=runtime_spec,
                labels=spec.labels(),
                random_tcp_ports=spec.tunnel_ports,
            )

    def rebuild(self, resource: Resource) -> None:
        spec = self.config.resource_spec(resource)
        if not isinstance(spec, WorkspaceSpec):
            raise ResourceNotFound(f"resource {resource.id!r} is not a workspace")
        with self.operations.run(resource.host, resource.id):
            self._rebuild_workspace(resource, spec)

    def _rebuild_workspace(self, resource: Resource, spec: WorkspaceSpec) -> None:
        def stage(message: str) -> None:
            self.operations.update(resource.host, resource.id, status="running", stage=message)

        stage("checking container")
        client = self.transport.client(resource.host)
        running = container.find_container(client, resource.container_name, labels=resource.labels)
        if running is None:
            raise ResourceNotFound(
                f"workspace container {resource.container_name!r} "
                f"not found on host {resource.host!r}"
            )
        actual = workspaces.read_workspace(running, resource.host)
        workspace_runtime.check_rebuild(actual, spec)
        credentials = self._provider_credentials(spec.source)
        route = self.transport.ssh_route(resource.host)
        names = self.config.hosts[resource.host].forward_environment
        forwarded: dict[str, str] = {}
        if names:
            stage("reading host environment")
            forwarded = host.read_environment(route, names)

        data = host.remote_data_paths(route)
        path = data.workspace(spec.project, spec.workspace)
        runtime_spec = workspace_runtime.container_spec(spec, path, forwarded)
        stage("checking secrets")
        runtime_spec.require_secrets(client)
        stage(f"pulling image {spec.image}")
        container.pull_image(client, runtime_spec.image, runtime_spec.platform, "always")
        stage("preparing data root")
        host.prepare_directories(
            route, list(dict.fromkeys([path, *runtime_spec.data_directories(path)]))
        )

        stage("replacing container")
        container.remove_container(running)
        self.transport.close_tcp(resource.host, actual.ssh_alias)
        ssh.remove_route(actual)
        stage("creating container")
        created = container.create_container(
            client, name=resource.container_name, spec=runtime_spec, labels=spec.labels()
        )
        workspace_runtime.bootstrap(spec, created, self.transport, path, credentials, stage)

    def inspect_deletion(self, resource: Resource) -> RepoGitState:
        running = self._container(resource)
        actual = workspaces.read_workspace(running, resource.host)
        return workspace_runtime.inspect_deletion(actual, self.transport, running)

    def remove(self, resource: Resource, *, purge: bool = False) -> bool:
        spec = self.config.resource_spec(resource)
        self._queue(resource)
        with self.operations.run(resource.host, resource.id, reraise=True):
            return self._remove(resource, spec, purge=purge)

    def _remove(
        self, resource: Resource, spec: WorkspaceSpec | ServiceSpec, *, purge: bool
    ) -> bool:
        self.operations.update(resource.host, resource.id, status="running", stage="removing")
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
        credentials = self._provider_credentials(actual.source)
        for source, token in credentials:
            try:
                provider.revoke(
                    source.type,
                    token,
                    source.repository,
                    actual.id,
                )
            except Exception as exc:
                logger.warning(
                    "failed to revoke deploy key for {} from {}:{}; "
                    "continuing Workspace removal because deleting the container "
                    "destroys its private key: {}",
                    actual.id,
                    source.type,
                    source.repository,
                    describe_error(exc),
                )
        if purge:
            data = host.remote_data_paths(self.transport.ssh_route(resource.host))
            running.stop(timeout=10, ignore=True)
            container.remove_data_directory(
                client,
                actual.image,
                data.workspaces,
                data.workspace(resource.project, resource.name),
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
            else self.config.service_tunnel_ports(resource.name)
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
        endpoint = container.published_tcp_endpoint(running, port)
        if endpoint is None:
            raise ResourceConflict(
                f"service {actual.id!r} does not publish tunnel port {port}; reapply it"
            )
        remote_host, remote_port = endpoint
        configured_publication = self.config.service_port_publication(
            resource.name,
            resource.host,
            port,
        )
        if configured_publication is not None and endpoint != configured_publication:
            raise ResourceConflict(
                f"service {actual.id!r} tunnel port {port} has stale publication metadata; "
                "reapply it"
            )
        return self.transport.forward_tcp(
            resource.host,
            route.host,
            port=remote_port,
            local_port=None if configured_publication is None else remote_port,
            remote_host=remote_host,
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
