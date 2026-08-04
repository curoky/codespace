"""Pydantic models for the supported Compose service subset.

``ServiceSpec`` is one Compose service block. Every field is optional, matching
Compose semantics where an unset key means "engine default"; the same optional
shape doubles as an override layer, so a single model covers both the base block
and the per-host/per-project overrides applied on top of it. Field names follow
Compose (``volumes``/``environment``) and accept Compose short syntax via the
``BeforeValidator`` parsers in :mod:`codespace.client.compose.syntax`.
"""

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
    """One resource limit, keyed by name in the ``ulimits`` mapping.

    Forwarded to ``podman run --ulimit``. A bare integer in the source YAML is
    normalized to equal ``soft`` and ``hard`` by the field's short-syntax parser.
    """

    model_config = ConfigDict(extra="forbid")

    soft: int
    hard: int


class Volume(BaseModel):
    """One bind mount in ``volumes`` (Compose long syntax).

    Only ``type: bind`` is supported; ``source``/``target`` must be absolute
    paths and ``read_only`` defaults to ``false``. The short syntax
    ``source:target[:ro|rw]`` is expanded to this shape before validation.
    """

    model_config = ConfigDict(extra="forbid")

    type: Annotated[str, Field(pattern="^bind$")] = "bind"
    source: AbsolutePath
    target: AbsolutePath
    read_only: bool = False


# Field types wired to the short-syntax parsers, shared across every field.
_Ulimits = Annotated[dict[NonBlankString, Ulimit], BeforeValidator(normalize_ulimits)]
_Volumes = Annotated[list[Volume], BeforeValidator(normalize_volumes)]
_Environment = Annotated[dict[str, str], BeforeValidator(normalize_environment)]


class ServiceSpec(BaseModel):
    """One Compose service block; every field is optional.

    An unset (``None``) field means "not specified": at the runtime boundary it
    maps to the container engine's default, and in ``merged_with`` it inherits
    the value from the layer below instead of overriding it. The same model is
    therefore used both for the base block and for override layers.
    """

    model_config = ConfigDict(extra="forbid")

    cap_add: list[NonBlankString] | None = None
    security_opt: list[NonBlankString] | None = None
    network_mode: NonBlankString | None = None
    pids_limit: int | None = None
    ulimits: _Ulimits | None = None
    volumes: _Volumes | None = None
    environment: _Environment | None = None
    devices: list[NonBlankString] | None = None

    def merged_with(self, *overrides: ServiceSpec | None) -> Self:
        """Return a copy with each override layer applied in order.

        Only the keys a layer actually sets replace the value below it (shallow,
        key-level replace; there is no deep merge, so e.g. a set ``environment``
        fully replaces the mapping below rather than being combined with it).
        Unset (``None``) keys inherit the value below. Layers are applied left to
        right, so a later layer wins over an earlier one. The result is
        re-validated, so it still honours every model constraint.
        """
        merged = self.model_dump(exclude_none=True)
        for override in overrides:
            if override is None:
                continue
            merged.update(override.model_dump(exclude_none=True))
        return self.__class__.model_validate(merged)
