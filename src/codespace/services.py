"""Service specifications and inventory from canonical Podman labels."""

from __future__ import annotations

from podman import PodmanClient
from podman.domain.containers import Container
from pydantic import BaseModel, ConfigDict

from codespace.resources import LABEL_IMAGE, LABEL_KIND, Resource
from codespace.runtime.container import ContainerSpec, container_status

LABEL_SERVICE = "codespace.service"


class ServiceMetadata(BaseModel):
    """Service identity and metadata shared by desired and deployed state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str
    host: str
    image: str

    @property
    def resource(self) -> Resource:
        return Resource(self.host, self.service)

    @property
    def id(self) -> str:
        return self.resource.id


class ServiceSpec(ServiceMetadata):
    """Resolved Service placement on one Host."""

    container: ContainerSpec
    tunnel_ports: list[int]

    def labels(self) -> dict[str, str]:
        return {**self.resource.labels, LABEL_IMAGE: self.image}


class Service(ServiceMetadata):
    """One actual Service container read from Podman labels."""

    container_id: str
    status: str


def list_services(client: PodmanClient, host: str) -> list[Service]:
    return sorted(
        (
            read_service(container, host)
            for container in client.containers.list(
                all=True, filters={"label": f"{LABEL_KIND}=service"}
            )
        ),
        key=lambda item: item.service,
    )


def read_service(container: Container, host: str) -> Service:
    return Service(
        service=container.labels[LABEL_SERVICE],
        host=host,
        image=container.labels[LABEL_IMAGE],
        container_id=container.id,
        status=container_status(container),
    )
