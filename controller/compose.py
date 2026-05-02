"""A small subset of the Compose service schema forwarded to ``podman run``.

Models only the container fields the control plane cares about (``cap_add``,
``security_opt``, ``pids_limit``, ``ulimits``, ``volumes``, ``environment``,
``secrets``, ...) using Compose field names and both short and long syntaxes.
Every field is optional so one ``ServiceSpec`` serves as both base and override
layer; ``merged_with`` does the shallow key-level layering. No control-plane
knowledge lives here.
"""

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

_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _absolute_path(value: str) -> str:
    if not value.startswith("/"):
        raise ValueError("must be an absolute path")
    return value


def _mount_source(value: str) -> str:
    """A bind-mount source: an absolute host path or a ``${VAR}`` placeholder."""
    if value.startswith(("/", "${")):
        return value
    raise ValueError("volume source must be an absolute path or a ${...} placeholder")


NonBlankString = Annotated[str, AfterValidator(_not_blank)]
AbsolutePath = Annotated[str, AfterValidator(_absolute_path)]
MountSource = Annotated[str, AfterValidator(_mount_source)]


def normalize_volumes(value: object) -> object:
    """Expand ``source:target[:ro|rw]`` bind mounts."""
    if not isinstance(value, list):
        return value
    return [_normalize_volume(item) for item in value]


def _normalize_volume(item: object) -> object:
    if not isinstance(item, str):
        return item
    parts = item.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"volume {item!r} must be 'source:target' or 'source:target:ro|rw'")
    source, target = parts[0], parts[1]
    read_only = False
    if len(parts) == 3:
        mode = parts[2]
        if mode not in ("ro", "rw"):
            raise ValueError(f"volume {item!r} mode must be 'ro' or 'rw', got {mode!r}")
        read_only = mode == "ro"
    return {"type": "bind", "source": source, "target": target, "read_only": read_only}


def normalize_environment(value: object) -> object:
    """Convert ``KEY=value`` list entries to a mapping."""
    if not isinstance(value, list):
        return value
    result: dict[str, str] = {}
    for entry in value:
        if not isinstance(entry, str) or "=" not in entry:
            raise ValueError(f"environment entry {entry!r} must be 'KEY=value'")
        key, _, val = entry.partition("=")
        if not key:
            raise ValueError(f"environment entry {entry!r} has an empty key")
        result[key] = val
    return result


def normalize_ulimits(value: object) -> object:
    """Expand scalar ulimits to equal soft and hard values."""
    if not isinstance(value, dict):
        return value
    return {name: _normalize_ulimit(limit) for name, limit in value.items()}


def _normalize_ulimit(limit: object) -> object:
    if isinstance(limit, bool):
        raise ValueError("ulimit value must be an integer or a {soft, hard} mapping")
    if isinstance(limit, int):
        return {"soft": limit, "hard": limit}
    return limit


def normalize_secrets(value: object) -> object:
    """Expand bare ``name`` secret references to mount entries."""
    if not isinstance(value, list):
        return value
    return [{"source": item, "mode": "mount"} if isinstance(item, str) else item for item in value]


class Ulimit(BaseModel):
    """Normalized Compose ulimit value."""

    model_config = ConfigDict(extra="forbid")

    soft: int
    hard: int


class Volume(BaseModel):
    """Normalized Compose bind mount."""

    model_config = ConfigDict(extra="forbid")

    type: Annotated[str, Field(pattern="^bind$")] = "bind"
    source: MountSource
    target: AbsolutePath
    read_only: bool = False


class Secret(BaseModel):
    """A reference to a Podman secret the host operator pre-created.

    The control plane never holds the material: ``source`` names the secret;
    ``mode: mount`` exposes it as a file, ``mode: env`` injects the env var named
    by ``target``.
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
    ipc: NonBlankString | None = None
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
            if override is not None:
                merged.update(override.model_dump(exclude_none=True))
        return self.__class__.model_validate(merged)
