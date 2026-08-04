"""Pydantic models for the supported Compose service subset.

``ServiceSpec`` is the fully-specified block; ``ServiceOverride`` is the
all-optional variant used for shallow, key-level overrides. Both use Compose
field names (``volumes``/``environment``) and accept Compose short syntax via
the ``BeforeValidator`` parsers in :mod:`codespace.client.compose.syntax`.
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


# Fields shared by ServiceSpec and ServiceOverride, wired to the short-syntax
# parsers. ServiceSpec makes the runtime flags required; ServiceOverride makes
# every field optional for shallow key-level overrides.
_Ulimits = Annotated[dict[NonBlankString, Ulimit], BeforeValidator(normalize_ulimits)]
_Volumes = Annotated[list[Volume], BeforeValidator(normalize_volumes)]
_Environment = Annotated[dict[str, str], BeforeValidator(normalize_environment)]


class ServiceSpec(BaseModel):
    """A fully specified container service.

    ``cap_add``/``security_opt``/``pids_limit``/``ulimits`` are required so a
    top-level service block declares them explicitly; ``volumes``/
    ``environment`` default to empty as the explicit "none" form.
    """

    model_config = ConfigDict(extra="forbid")

    cap_add: list[NonBlankString]
    security_opt: list[NonBlankString]
    pids_limit: int
    ulimits: _Ulimits
    volumes: _Volumes = Field(default_factory=list)
    environment: _Environment = Field(default_factory=dict)

    def merged_with(self, *overrides: ServiceOverride | None) -> Self:
        """Return a copy with each override layer applied in order.

        Every set override key replaces the corresponding value wholesale
        (shallow, key-level replace; there is no deep merge, so e.g. a set
        ``environment`` fully replaces the base mapping rather than being
        combined with it). Unset keys inherit the current value. Layers are
        applied left to right, so a later layer wins over an earlier one. The
        result is re-validated, so it still honours every model constraint.
        """
        merged = self.model_dump()
        for override in overrides:
            if override is None:
                continue
            merged.update(override.model_dump(exclude_none=True))
        return self.__class__.model_validate(merged)


class ServiceOverride(BaseModel):
    """Optional override of a ``ServiceSpec``; every field is optional.

    Each set key replaces the corresponding base value wholesale (shallow,
    key-level replace; no deep merge). Unset keys inherit the base value.
    """

    model_config = ConfigDict(extra="forbid")

    cap_add: list[NonBlankString] | None = None
    security_opt: list[NonBlankString] | None = None
    pids_limit: int | None = None
    ulimits: _Ulimits | None = None
    volumes: _Volumes | None = None
    environment: _Environment | None = None
