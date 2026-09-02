"""Read Service containers from the canonical Podman labels."""

from __future__ import annotations

from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import NotFound

from codespace.services.models import (
    LABEL_IMAGE,
    LABEL_KIND,
    LABEL_SERVICE,
    SERVICE_KIND,
    Service,
    ServiceSpec,
    service_identity,
)
from codespace.workspaces.inventory import container_status


def list_services(client: PodmanClient, host: str) -> list[Service]:
    containers = client.containers.list(
        all=True,
        filters={"label": f"{LABEL_KIND}={SERVICE_KIND}"},
    )
    services = [read_service(container, host) for container in containers]
    services.sort(key=lambda item: item.service)
    return services


def read_service(container: Container, host: str) -> Service:
    labels = container.labels or {}
    service = labels[LABEL_SERVICE]
    return Service(
        id=service_identity(service),
        service=service,
        host=host,
        image=labels[LABEL_IMAGE],
        container_id=container.id,
        status=container_status(container),
    )


def find_container(client: PodmanClient, spec: ServiceSpec) -> Container | None:
    try:
        return client.containers.get(spec.identity)
    except NotFound:
        return None
