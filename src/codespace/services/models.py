"""Service identities, resolved specifications, and inventory models."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from codespace.runtime.container import ContainerSpec

LABEL_KIND = "codespace.kind"
LABEL_SERVICE = "codespace.service"
LABEL_IMAGE = "codespace.image"
SERVICE_KIND = "service"
SERVICE_DATA_PLACEHOLDER = "${SERVICE_DATA}"


def service_identity(service: str) -> str:
    return f"codespace-service-{service}"


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """Resolved Service placement on one Host."""

    service: str
    host: str
    image: str
    container: ContainerSpec

    @property
    def identity(self) -> str:
        return service_identity(self.service)

    def labels(self) -> dict[str, str]:
        return {
            LABEL_KIND: SERVICE_KIND,
            LABEL_SERVICE: self.service,
            LABEL_IMAGE: self.image,
        }


class Service(BaseModel):
    """One actual Service container read from Podman labels."""

    model_config = ConfigDict(extra="forbid")

    id: str
    service: str
    host: str
    image: str
    container_id: str
    status: str | None = None
