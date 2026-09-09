"""Read Service containers from the canonical Podman labels."""

from __future__ import annotations

from podman import PodmanClient
from podman.domain.containers import Container

from codespace.runtime.container import container_status
from codespace.services.models import (
    LABEL_IMAGE,
    LABEL_KIND,
    LABEL_SERVICE,
    SERVICE_KIND,
    Service,
    service_identity,
)


def list_services(client: PodmanClient, host: str) -> list[Service]:
    containers = client.containers.list(
        all=True,
        filters={"label": f"{LABEL_KIND}={SERVICE_KIND}"},
    )
    services = [read_service(container, host) for container in containers]
    services.sort(key=lambda item: item.service)
    return services


def read_service(container: Container, host: str) -> Service:
    labels = container.labels
    service = labels[LABEL_SERVICE]
    return Service(
        id=service_identity(service),
        service=service,
        host=host,
        image=labels[LABEL_IMAGE],
        container_id=container.id,
        status=container_status(container),
    )
