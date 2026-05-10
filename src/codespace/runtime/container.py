"""Canonical container configuration and Podman runtime primitives."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator, Mapping
from typing import Annotated, Any, Literal, Self, cast

from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import PodmanError
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_fixed

_READY_TIMEOUT = 30.0
_READY_INTERVAL = 0.25
_PULL_TIMEOUT = 15 * 60.0
_LOG_TAIL = 2000
_PORT_MIN = 1
_PORT_MAX = 65_535
_ENVIRONMENT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _absolute_path(value: str) -> str:
    if not value.startswith("/"):
        raise ValueError("must be an absolute path")
    return value


def _mount_source(value: str) -> str:
    if value.startswith(("/", "${")):
        return value
    raise ValueError("volume source must be an absolute path or a ${...} placeholder")


type NonBlankString = Annotated[str, AfterValidator(_not_blank)]
type AbsolutePath = Annotated[str, AfterValidator(_absolute_path)]
type MountSource = Annotated[str, AfterValidator(_mount_source)]
type ImagePlatform = Literal["linux/amd64", "linux/arm64"]


class UlimitSpec(BaseModel):
    """Soft and hard limits for one named resource."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    soft: int
    hard: int


class VolumeSpec(BaseModel):
    """One normalized Compose bind mount."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["bind"]
    source: MountSource
    target: AbsolutePath
    read_only: bool = False

    @model_validator(mode="before")
    @classmethod
    def _expand_short_syntax(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        parts = value.split(":")
        if len(parts) not in (2, 3):
            raise ValueError(f"volume {value!r} must be 'source:target' or 'source:target:ro|rw'")
        if len(parts) == 3 and parts[2] not in ("ro", "rw"):
            raise ValueError(f"volume {value!r} mode must be 'ro' or 'rw', got {parts[2]!r}")
        return {
            "type": "bind",
            "source": parts[0],
            "target": parts[1],
            "read_only": len(parts) == 3 and parts[2] == "ro",
        }


class SecretSpec(BaseModel):
    """One named reference to a pre-registered Podman secret."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: NonBlankString
    mode: Literal["mount", "env"] = "mount"
    target: NonBlankString | None = None
    uid: int | None = None
    gid: int | None = None
    file_mode: int | None = Field(default=None, ge=0, le=0o777)

    @model_validator(mode="after")
    def _validate_target(self) -> Self:
        if self.mode == "env":
            if self.target is None:
                raise ValueError(f"secret {self.source!r} with mode 'env' requires 'target'")
            if not _ENVIRONMENT_NAME_RE.fullmatch(self.target):
                raise ValueError(f"secret env target {self.target!r} is not a valid variable name")
            if self.uid is not None or self.gid is not None or self.file_mode is not None:
                raise ValueError("env secrets must not set uid, gid, or file_mode")
        elif self.target is not None and not self.target.startswith("/"):
            raise ValueError("mount secret target must be an absolute path")
        return self


class PortSpec(BaseModel):
    """One loopback-only host port mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host: int = Field(ge=_PORT_MIN, le=_PORT_MAX)
    container: int = Field(ge=_PORT_MIN, le=_PORT_MAX)
    protocol: Literal["tcp", "udp"] = "tcp"


class ContainerSpec(BaseModel):
    """Canonical, all-optional container layer.

    Layers are merged by field. Lists and mappings replace the previous value
    wholesale, which keeps placement resolution explicit and deterministic.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    cap_add: list[NonBlankString] | None = None
    security_opt: list[NonBlankString] | None = None
    network_mode: Literal["host", "bridge"] | None = None
    ipc: NonBlankString | None = None
    pids_limit: int | None = None
    ulimits: dict[NonBlankString, UlimitSpec] | None = None
    volumes: list[VolumeSpec] | None = None
    environment: dict[NonBlankString, str] | None = None
    secrets: dict[NonBlankString, SecretSpec] | None = None
    devices: list[NonBlankString] | None = None
    ports: dict[NonBlankString, PortSpec] | None = None
    shm_size: NonBlankString | None = None

    @property
    def is_bridge(self) -> bool:
        return self.network_mode == "bridge"

    def merged_with(self, *overrides: ContainerSpec | None) -> Self:
        merged = self.model_dump(exclude_none=True)
        for override in overrides:
            if override is not None:
                merged.update(override.model_dump(exclude_none=True))
        return self.__class__.model_validate(merged)


def configured_mounts(
    volumes: list[VolumeSpec] | None,
    *,
    placeholders: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    """Translate configured volumes and resolve the explicitly allowed placeholders."""
    resolved: list[dict[str, object]] = []
    replacements = placeholders or {}
    for volume in volumes or []:
        source = volume.source
        if source.startswith("${"):
            try:
                source = replacements[source]
            except KeyError as exc:
                raise ValueError(f"unknown volume source placeholder {source!r}") from exc
        resolved.append(
            {
                "type": "bind",
                "source": source,
                "target": volume.target,
                "read_only": volume.read_only,
            }
        )
    return resolved


def create_container(
    client: PodmanClient,
    image: str,
    *,
    name: str,
    spec: ContainerSpec,
    environment: Mapping[str, str],
    labels: Mapping[str, str],
    mounts: list[dict[str, object]],
    platform: ImagePlatform | None = None,
    extra_ports: Mapping[str, object] | None = None,
    volume_placeholders: Mapping[str, str] | None = None,
    restart_policy: Mapping[str, object] | None = None,
    secret_uid: int = 0,
    secret_gid: int = 0,
) -> Container:
    """Create a detached container from a fully resolved canonical specification."""
    secret_mounts, secret_env = _resolve_secrets(
        client,
        spec.secrets or {},
        default_uid=secret_uid,
        default_gid=secret_gid,
    )
    ports: dict[str, object] = {
        f"{port.container}/{port.protocol}": ("127.0.0.1", port.host)
        for port in (spec.ports or {}).values()
    }
    ports.update(extra_ports or {})
    options: dict[str, Any] = {
        "name": name,
        "network_mode": spec.network_mode,
        "cap_add": spec.cap_add or [],
        "security_opt": spec.security_opt or [],
        "ulimits": [
            {"Name": resource, "Soft": limit.soft, "Hard": limit.hard}
            for resource, limit in (spec.ulimits or {}).items()
        ],
        "environment": dict(environment),
        "devices": spec.devices or [],
        "ports": ports if spec.is_bridge else {},
        "labels": dict(labels),
        "mounts": [
            *mounts,
            *configured_mounts(spec.volumes, placeholders=volume_placeholders),
        ],
    }
    if platform is not None:
        options["platform"] = platform
    if restart_policy is not None:
        options["restart_policy"] = dict(restart_policy)
    if spec.pids_limit is not None:
        options["pids_limit"] = spec.pids_limit
    if spec.shm_size is not None:
        options["shm_size"] = spec.shm_size
    if spec.ipc is not None:
        options["ipc_mode"] = spec.ipc
    if secret_mounts:
        options["secrets"] = secret_mounts
    if secret_env:
        options["secret_env"] = secret_env
    return run_container(client, image, options)


def _resolve_secrets(
    client: PodmanClient,
    secrets: Mapping[str, SecretSpec],
    *,
    default_uid: int,
    default_gid: int,
) -> tuple[list[dict[str, object]], dict[str, str]]:
    mounts: list[dict[str, object]] = []
    environment: dict[str, str] = {}
    for secret in secrets.values():
        require_secret(client, secret.source)
        if secret.mode == "env":
            if secret.target is None:
                raise ValueError(f"env secret {secret.source!r} has no target")
            environment[secret.target] = secret.source
            continue
        mount: dict[str, object] = {
            "source": secret.source,
            "uid": secret.uid if secret.uid is not None else default_uid,
            "gid": secret.gid if secret.gid is not None else default_gid,
            "mode": secret.file_mode if secret.file_mode is not None else 0o400,
        }
        if secret.target is not None:
            mount["target"] = secret.target
        mounts.append(mount)
    return mounts, environment


def require_secret(client: PodmanClient, name: str) -> None:
    if not client.secrets.exists(name):
        raise RuntimeError(
            f"Podman secret {name!r} is not registered on the host; "
            "run `codespace secrets sync --apply` first"
        )


def pull_image(client: PodmanClient, image: str, platform: ImagePlatform | None) -> None:
    """Pull an image while surfacing errors from the streaming API."""
    kwargs: dict[str, Any] = {"stream": True, "decode": True}
    if platform is not None:
        kwargs["platform"] = platform
    pull_client = PodmanClient(
        base_url=client.api.base_url.geturl(),
        version=client.api.version,
        timeout=_PULL_TIMEOUT,
    )
    try:
        events = cast("Iterator[dict[str, str]]", pull_client.images.pull(image, **kwargs))
        for event in events:
            error = event.get("error") if isinstance(event, dict) else None
            if error:
                raise PodmanError(f"failed to pull {image}: {error}")
    finally:
        pull_client.close()  # type: ignore[no-untyped-call]


def run_container(client: PodmanClient, image: str, options: dict[str, Any]) -> Container:
    created = client.containers.run(image, detach=True, **options)
    if not isinstance(created, Container):
        raise TypeError(f"expected Container, got {type(created)}")
    wait_running(created)
    return created


def remove_data_directory(
    client: PodmanClient,
    image: str,
    data_root: str,
    target: str,
    *,
    platform: ImagePlatform | None = None,
) -> None:
    """Remove one directory strictly below a managed data root."""
    normalized_root = posixpath.normpath(data_root)
    normalized_target = posixpath.normpath(target)
    if (
        not normalized_root.startswith("/")
        or not normalized_target.startswith("/")
        or posixpath.commonpath((normalized_root, normalized_target)) != normalized_root
        or normalized_target == normalized_root
    ):
        raise RuntimeError(f"refusing to remove {target!r} outside root {data_root!r}")
    helper = client.containers.run(
        image,
        name=None,
        entrypoint=["/bin/rm"],
        command=["-rf", "--", normalized_target],
        detach=True,
        platform=platform,
        user="0",
        security_opt=["disable"],
        mounts=[{"type": "bind", "source": normalized_root, "target": normalized_root}],
    )
    if not isinstance(helper, Container):
        raise RuntimeError("expected a detached directory-removal container")
    try:
        exit_code = helper.wait()
        if exit_code not in (0, None):
            logs = helper.logs(stdout=True, stderr=True)
            raw = logs if isinstance(logs, bytes) else b"".join(logs)
            detail = raw.decode("utf-8", "replace").strip()
            raise RuntimeError(f"failed to remove {target!r} ({exit_code}): {detail}")
    finally:
        helper.remove(force=True)


def remove_container(container: Container) -> None:
    container.remove(force=True)


def container_logs(container: Container) -> str:
    result = container.logs(
        stdout=True,
        stderr=True,
        stream=False,
        timestamps=True,
        tail=_LOG_TAIL,
    )
    raw = result if isinstance(result, bytes) else b"".join(result)
    return raw.decode("utf-8", "replace")


class _ContainerNotRunning(Exception):
    pass


def wait_running(container: Container) -> None:
    try:
        _reload_until_running(container)
    except _ContainerNotRunning as exc:
        raise RuntimeError(str(exc)) from None


@retry(
    retry=retry_if_exception_type(_ContainerNotRunning),
    stop=stop_after_delay(_READY_TIMEOUT),
    wait=wait_fixed(_READY_INTERVAL),
    reraise=True,
)
def _reload_until_running(container: Container) -> None:
    container.reload()
    if container.status != "running":
        name = str(getattr(container, "name", None) or container.id)
        raise _ContainerNotRunning(f"container {name} did not reach running state")
