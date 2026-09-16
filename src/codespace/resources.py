"""Host-scoped identities shared by Service and Workspace operations."""

import re
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

RESOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
type ResourceId = Annotated[str, Field(pattern=RESOURCE_ID_RE.pattern)]
type HostId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9.-]{0,62}$")]

type ResourceKind = Literal["workspace", "service"]
LABEL_KIND = "codespace.kind"
LABEL_IMAGE = "codespace.image"


class ResourceNotFound(Exception):
    """The requested resource or configured placement does not exist."""


class ResourceConflict(Exception):
    """The resource state prevents the requested operation."""


@dataclass(frozen=True, slots=True)
class Resource:
    """A Service singleton, or a named Workspace belonging to a Project."""

    host: str
    name: str
    project: str | None = None

    @property
    def kind(self) -> ResourceKind:
        return "service" if self.project is None else "workspace"

    @property
    def id(self) -> str:
        if self.project is None:
            return self.container_name
        return f"space:{self.project}/{self.name}@{self.host}"

    @property
    def container_name(self) -> str:
        if self.project is None:
            return f"codespace-service-{self.name}"
        return f"space-{self.project}-{self.name}"

    @property
    def labels(self) -> dict[str, str]:
        labels = {LABEL_KIND: self.kind, f"codespace.{self.kind}": self.name}
        if self.project is not None:
            labels["codespace.project"] = self.project
        return labels
