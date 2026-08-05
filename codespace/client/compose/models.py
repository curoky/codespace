"""Pydantic models for the supported Compose service subset."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
)

from codespace.client.compose.syntax import (
    normalize_environment,
    normalize_ulimits,
    normalize_volumes,
)


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _absolute_path(value: str) -> str:
    if not value.startswith("/"):
        raise ValueError("must be an absolute path")
    return value


NonBlankString = Annotated[str, AfterValidator(_not_blank)]
AbsolutePath = Annotated[str, AfterValidator(_absolute_path)]


class Ulimit(BaseModel):
    """Normalized Compose ulimit value."""

    model_config = ConfigDict(extra="forbid")

    soft: int
    hard: int


class Volume(BaseModel):
    """Normalized Compose bind mount."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[str, Field(pattern="^bind$")] = "bind"
    source: AbsolutePath
    target: AbsolutePath
    read_only: bool = False


_Ulimits = Annotated[dict[NonBlankString, Ulimit], BeforeValidator(normalize_ulimits)]
_Volumes = Annotated[list[Volume], BeforeValidator(normalize_volumes)]
_Environment = Annotated[dict[str, str], BeforeValidator(normalize_environment)]


class ServiceSpec(BaseModel):
    """All-optional Compose service block used for base and override layers."""

    model_config = ConfigDict(extra="forbid")

    cap_add: list[NonBlankString] | None = None
    security_opt: list[NonBlankString] | None = None
    network_mode: NonBlankString | None = None
    pids_limit: int | None = None
    ulimits: _Ulimits | None = None
    volumes: _Volumes | None = None
    environment: _Environment | None = None
    devices: list[NonBlankString] | None = None
    shm_size: NonBlankString | None = None

    def merged_with(self, *overrides: ServiceSpec | None) -> Self:
        """Apply shallow override layers left to right and revalidate."""
        merged = self.model_dump(exclude_none=True)
        for override in overrides:
            if override is None:
                continue
            merged.update(override.model_dump(exclude_none=True))
        return self.__class__.model_validate(merged)
