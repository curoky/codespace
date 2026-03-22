"""Pydantic models for the supported Compose service subset."""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    model_validator,
)

from controller.runtime.compose.syntax import (
    normalize_environment,
    normalize_secrets,
    normalize_ulimits,
    normalize_volumes,
)

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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


class Secret(BaseModel):
    """Normalized reference to a Podman secret registered on the host.

    The control plane never holds the secret material: ``source`` names a secret
    the host operator pre-created with ``podman secret create``. ``mode: mount``
    exposes it as a file (default ``/run/secrets/<source>``); ``mode: env``
    injects it as the environment variable named by ``target``.
    """

    model_config = ConfigDict(extra="forbid")

    source: NonBlankString
    mode: Literal["mount", "env"] = "mount"
    target: NonBlankString | None = None
    uid: int | None = None
    gid: int | None = None
    file_mode: int | None = None

    @model_validator(mode="after")
    def _validate_mode_fields(self) -> Self:
        if self.mode == "env":
            if self.target is None:
                raise ValueError(f"secret {self.source!r} with mode 'env' requires 'target'")
            if not _ENV_NAME_RE.match(self.target):
                raise ValueError(
                    f"secret {self.source!r} env target {self.target!r} must match "
                    r"^[A-Za-z_][A-Za-z0-9_]*$"
                )
            if self.uid is not None or self.gid is not None or self.file_mode is not None:
                raise ValueError(
                    f"secret {self.source!r} with mode 'env' must not set uid/gid/file_mode"
                )
        elif self.target is not None and not self.target.startswith("/"):
            raise ValueError(
                f"secret {self.source!r} mount target {self.target!r} must be an absolute path"
            )
        return self


_Ulimits = Annotated[dict[NonBlankString, Ulimit], BeforeValidator(normalize_ulimits)]
_Volumes = Annotated[list[Volume], BeforeValidator(normalize_volumes)]
_Environment = Annotated[dict[str, str], BeforeValidator(normalize_environment)]
_Secrets = Annotated[list[Secret], BeforeValidator(normalize_secrets)]


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
    secrets: _Secrets | None = None
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
