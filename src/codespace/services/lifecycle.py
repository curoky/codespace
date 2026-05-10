"""Service lifecycle orchestration."""

from __future__ import annotations

from collections.abc import Callable

from loguru import logger

from codespace.config import Config
from codespace.operations import Operation, OperationStore, describe_error
from codespace.runtime import container, host
from codespace.runtime.transport import PodmanTransport
from codespace.services import inventory
from codespace.services.models import SERVICE_DATA_PLACEHOLDER, Service, ServiceSpec


class ServiceManager:
    """Own Service inventory, reconcile, removal, logs, and operations."""

    def __init__(
        self,
        config: Config,
        transport: PodmanTransport,
        *,
        operations: OperationStore | None = None,
    ) -> None:
        self.config = config
        self.transport = transport
        self.operations = operations or OperationStore()

    def inventory(self, host_name: str) -> list[Service]:
        return inventory.list_services(self.transport.client(host_name), host_name)

    def queue_apply(self, service: str, host_name: str) -> Operation:
        self._service(service, host_name)
        spec = self.config.service_spec(service, host_name)
        return self.operations.create(
            Operation(
                id=spec.identity,
                kind="service",
                host=host_name,
                resource=service,
                status="queued",
                stage="queued",
            )
        )

    def dismiss_failed(self, service: str, host_name: str) -> bool:
        self._service(service, host_name)
        return self.operations.dismiss_failed(
            host_name,
            self.config.service_spec(service, host_name).identity,
        )

    def apply(self, service: str, host_name: str) -> None:
        spec = self.config.service_spec(service, host_name)
        self._run_operation(spec, lambda: self._apply(spec))

    def _apply(self, spec: ServiceSpec) -> None:
        client = self.transport.client(spec.host)
        route = self.transport.ssh_route(spec.host)
        self._stage(spec, "checking inventory", running=True)
        managed = inventory.list_services(client, spec.host)
        existing = inventory.find_container(client, spec)
        if existing is not None and all(item.id != spec.identity for item in managed):
            raise RuntimeError(
                f"container {spec.identity!r} exists without the required Service labels"
            )

        self._stage(spec, f"pulling image {spec.image}")
        container.pull_image(client, spec.image, None)

        self._stage(spec, "preparing data root")
        data_paths = host.remote_data_paths(route)
        data_path = data_paths.service(spec.service)
        host.prepare_directories(route, [data_path])

        self._stage(spec, "replacing container")
        if existing is not None:
            container.remove_container(existing)

        self._stage(spec, "creating container")
        container.create_container(
            client,
            spec.image,
            name=spec.identity,
            spec=spec.container,
            environment=spec.container.environment or {},
            labels=spec.labels(),
            mounts=[],
            volume_placeholders={SERVICE_DATA_PLACEHOLDER: data_path},
            restart_policy={"Name": "unless-stopped"},
        )

    def remove(self, service: str, host_name: str, *, purge: bool = False) -> bool:
        self._service(service, host_name)
        spec = self.config.service_spec(service, host_name)
        client = self.transport.client(host_name)
        managed = inventory.list_services(client, host_name)
        running = inventory.find_container(client, spec)
        if running is not None and all(item.id != spec.identity for item in managed):
            raise RuntimeError(
                f"container {spec.identity!r} exists without the required Service labels"
            )
        removed = running is not None
        if running is not None:
            container.remove_container(running)
        if purge:
            data_paths = host.remote_data_paths(self.transport.ssh_route(host_name))
            container.remove_data_directory(
                client,
                spec.image,
                data_paths.services,
                data_paths.service(service),
            )
        return removed

    def logs(self, service: str, host_name: str) -> str:
        self._service(service, host_name)
        spec = self.config.service_spec(service, host_name)
        client = self.transport.client(host_name)
        managed = inventory.list_services(client, host_name)
        if all(item.id != spec.identity for item in managed):
            raise RuntimeError(f"service {service!r} not found on host {host_name!r}")
        running = inventory.find_container(client, spec)
        if running is None:
            raise RuntimeError(f"service {service!r} not found on host {host_name!r}")
        return container.container_logs(running)

    def _service(self, service: str, host_name: str) -> None:
        if service not in self.config.services:
            raise KeyError(f"unknown service: {service}")
        allowed = self.config.service_hosts(service)
        if host_name not in allowed:
            raise KeyError(
                f"host {host_name!r} is not configured for service {service!r}; allowed: {allowed}"
            )

    def _run_operation(self, spec: ServiceSpec, work: Callable[[], object]) -> None:
        try:
            work()
        except Exception as exc:
            logger.exception("failed Service operation {} on Host {}", spec.identity, spec.host)
            self.operations.update(
                spec.host,
                spec.identity,
                status="failed",
                stage="failed",
                error=describe_error(exc),
            )
            return
        self.operations.remove(spec.host, spec.identity)

    def _stage(self, spec: ServiceSpec, stage: str, *, running: bool = False) -> None:
        self.operations.update(
            spec.host,
            spec.identity,
            status="running" if running else None,
            stage=stage,
        )
