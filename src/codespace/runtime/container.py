"""Resolved container specifications and Podman runtime primitives."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal, Self, cast

from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import NotFound, PodmanError
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    model_validator,
)
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_fixed

_READY_TIMEOUT = 30.0
_READY_INTERVAL = 0.25
_PULL_TIMEOUT = 15 * 60.0
_LOG_TAIL = 2000
_LOG_FILE_LIMIT = 1024 * 1024
_LOG_FILE_RE = re.compile(r"^s6\.[A-Za-z0-9][A-Za-z0-9._-]*\.log$", re.ASCII)
_PORT_MIN = 1
_PORT_MAX = 65_535
_SECRET_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
CONTAINER_LOG_SOURCE = "container"


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _absolute_path(value: str) -> str:
    path = PurePosixPath(value)
    if not path.is_absolute():
        raise ValueError("must be an absolute path")
    if ".." in path.parts:
        raise ValueError("must not contain '..'")
    if "$" in value:
        raise ValueError("Compose variable interpolation is not supported")
    return str(path)


def _compose_literal(value: str) -> str:
    if "$" in value:
        raise ValueError("Compose variable interpolation is not supported")
    return value


def _secret_name(value: str) -> str:
    if not _SECRET_NAME_RE.fullmatch(value):
        raise ValueError("must be a valid Compose secret name")
    return value


def _secret_mode(value: int) -> int:
    return value & ~0o222


def _host_ip(value: str) -> str:
    return str(ip_address(value))


type NonBlankString = Annotated[str, AfterValidator(_not_blank)]
type ComposeString = Annotated[str, AfterValidator(_compose_literal)]
type ComposeNonBlankString = Annotated[
    str,
    AfterValidator(_not_blank),
    AfterValidator(_compose_literal),
]
type AbsolutePath = Annotated[str, AfterValidator(_absolute_path)]
type SecretName = Annotated[str, AfterValidator(_secret_name)]
type SecretId = Annotated[str, Field(pattern=r"^\d+$")]
type UlimitName = Annotated[str, Field(pattern=r"^[a-z]+$")]
type SecretMode = Annotated[
    StrictInt,
    Field(ge=0, le=0o777),
    AfterValidator(_secret_mode),
]
type ImagePlatform = Literal["linux/amd64", "linux/arm64"]


@dataclass(frozen=True, slots=True)
class LogSnapshot:
    """One bounded log view and the sources available in its container."""

    source: str
    sources: tuple[str, ...]
    logs: str


class UlimitSpec(BaseModel):
    """Soft and hard limits for one named resource."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    soft: StrictInt
    hard: StrictInt


class VolumeSpec(BaseModel):
    """One normalized Compose bind mount."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["bind"]
    source: NonBlankString
    target: AbsolutePath
    read_only: StrictBool = False

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

    def mount(self) -> dict[str, object]:
        """Produce a Podman mount only after its source is an absolute path."""
        return {
            "type": self.type,
            "source": _absolute_path(self.source),
            "target": self.target,
            "read_only": self.read_only,
        }


class SecretSpec(BaseModel):
    """Supported subset of Compose service secret long syntax."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SecretName
    target: AbsolutePath | None = None
    uid: SecretId | None = None
    gid: SecretId | None = None
    mode: SecretMode = 0o444


class PortSpec(BaseModel):
    """Supported subset of Compose service port long syntax."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: StrictInt = Field(ge=_PORT_MIN, le=_PORT_MAX)
    published: StrictInt = Field(ge=_PORT_MIN, le=_PORT_MAX)
    host_ip: Annotated[str, AfterValidator(_host_ip)]
    protocol: Literal["tcp", "udp"] = "tcp"


def _unique_options(values: list[str]) -> list[str]:
    if len(values) != len(set(values)):
        raise ValueError("must not contain duplicate values")
    return values


def _unique_volumes(volumes: list[VolumeSpec]) -> list[VolumeSpec]:
    keys = [(volume.type, volume.source, volume.target, volume.read_only) for volume in volumes]
    if len(keys) != len(set(keys)):
        raise ValueError("volumes must not contain duplicate values")
    return volumes


def _unique_ports(ports: list[PortSpec]) -> list[PortSpec]:
    destinations: set[tuple[int, str]] = set()
    for port in ports:
        destination = (port.target, port.protocol)
        if destination in destinations:
            raise ValueError(
                f"port target {port.target}/{port.protocol} is published more than once"
            )
        destinations.add(destination)
    return ports


type UniqueContainerOptions = Annotated[
    list[ComposeNonBlankString], AfterValidator(_unique_options)
]
type ContainerVolumes = Annotated[list[VolumeSpec], AfterValidator(_unique_volumes)]
type ContainerPorts = Annotated[list[PortSpec], AfterValidator(_unique_ports)]


class ContainerSpec(BaseModel):
    """Resolved placement with concrete collections and an explicit network mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cap_add: UniqueContainerOptions = Field(default_factory=list)
    security_opt: UniqueContainerOptions = Field(default_factory=list)
    network_mode: Literal["host", "bridge"]
    ipc: ComposeNonBlankString | None = None
    pids_limit: StrictInt | None = None
    ulimits: dict[UlimitName, UlimitSpec] = Field(default_factory=dict)
    volumes: ContainerVolumes = Field(default_factory=list)
    environment: dict[NonBlankString, ComposeString] = Field(default_factory=dict)
    secrets: list[SecretSpec] = Field(default_factory=list)
    devices: list[ComposeNonBlankString] = Field(default_factory=list)
    ports: ContainerPorts = Field(default_factory=list)
    shm_size: ComposeNonBlankString | None = None

    @model_validator(mode="after")
    def _validate_network(self) -> Self:
        if self.ports and not self.is_bridge:
            raise ValueError("ports may be published only in bridge mode")
        return self

    @property
    def is_bridge(self) -> bool:
        return self.network_mode == "bridge"


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
    restart_policy: Mapping[str, object] | None = None,
) -> Container:
    """Create a detached container from a fully resolved canonical specification."""
    secret_mounts = _resolve_secrets(client, spec.secrets)
    ports: dict[str, object] = {
        f"{port.target}/{port.protocol}": (port.host_ip, port.published) for port in spec.ports
    }
    options: dict[str, Any] = {
        "name": name,
        "network_mode": spec.network_mode,
        "cap_add": spec.cap_add,
        "security_opt": spec.security_opt,
        "ulimits": [
            {"Name": resource, "Soft": limit.soft, "Hard": limit.hard}
            for resource, limit in spec.ulimits.items()
        ],
        "environment": dict(environment),
        "devices": spec.devices,
        "ports": ports,
        "labels": dict(labels),
        "mounts": [
            *mounts,
            *(volume.mount() for volume in spec.volumes),
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
    return run_container(client, image, options)


def _resolve_secrets(
    client: PodmanClient,
    secrets: Sequence[SecretSpec],
) -> list[dict[str, object]]:
    mounts: list[dict[str, object]] = []
    for secret in secrets:
        require_secret(client, secret.source)
        mount: dict[str, object] = {
            "source": secret.source,
            "uid": int(secret.uid) if secret.uid is not None else 0,
            "gid": int(secret.gid) if secret.gid is not None else 0,
            "mode": secret.mode,
        }
        if secret.target is not None:
            mount["target"] = secret.target
        mounts.append(mount)
    return mounts


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
            error = event.get("error")
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
        if exit_code != 0:
            detail = container_logs(helper).strip()
            raise RuntimeError(f"failed to remove {target!r} ({exit_code}): {detail}")
    finally:
        helper.remove(force=True)


def remove_container(container: Container) -> None:
    container.remove(force=True)


def find_container(
    client: PodmanClient, name: str, *, labels: Mapping[str, str]
) -> Container | None:
    """Look up a deterministic name and verify ownership before any operation."""
    try:
        found = client.containers.get(name)
    except NotFound:
        return None
    if any(found.labels.get(key) != value for key, value in labels.items()):
        raise RuntimeError(f"container {name!r} exists without the required labels")
    return found


def container_status(container: Container) -> str:
    # Libpod list returns State as a string; inspect returns State.Status.
    state = container.attrs["State"]
    return cast("str", state if isinstance(state, str) else state["Status"])


def container_logs(container: Container) -> str:
    result = container.logs(
        stdout=True,
        stderr=True,
        stream=False,
        timestamps=True,
        tail=_LOG_TAIL,
    )
    raw = b"".join(cast("Iterator[bytes]", result))
    return raw.decode("utf-8", "replace")


def container_log_snapshot(
    container: Container,
    source: str = CONTAINER_LOG_SOURCE,
) -> LogSnapshot:
    if source != CONTAINER_LOG_SOURCE and not _LOG_FILE_RE.fullmatch(source):
        raise RuntimeError(f"invalid container log source: {source!r}")

    files = _container_log_files(container)
    sources = (CONTAINER_LOG_SOURCE, *files)
    if source not in sources:
        raise RuntimeError(f"container log source {source!r} not found")

    if source == CONTAINER_LOG_SOURCE:
        logs = container_logs(container)
    else:
        logs = _container_file_logs(container, source)
    return LogSnapshot(source=source, sources=sources, logs=logs)


def _container_log_files(container: Container) -> tuple[str, ...]:
    raw = _container_exec(
        container,
        [
            "find",
            "/var/log",
            "-maxdepth",
            "1",
            "-type",
            "f",
            "-name",
            "s6.*.log",
            "-printf",
            "%f\\0",
        ],
        action="list container log files",
    )
    files = []
    for encoded in raw.split(b"\0"):
        if not encoded:
            continue
        name = encoded.decode("utf-8", "replace")
        if not _LOG_FILE_RE.fullmatch(name):
            raise RuntimeError(f"container returned invalid log source: {name!r}")
        files.append(name)
    return tuple(sorted(set(files)))


def _container_file_logs(container: Container, source: str) -> str:
    raw = _container_exec(
        container,
        ["tail", f"--bytes={_LOG_FILE_LIMIT}", "--", f"/var/log/{source}"],
        action=f"read container log source {source!r}",
    )
    return raw.decode("utf-8", "replace")


def _container_exec(container: Container, command: list[str], *, action: str) -> bytes:
    exit_code, output = container.exec_run(
        command,
        stdout=True,
        stderr=True,
        stream=False,
        demux=True,
    )
    if not isinstance(output, tuple) or len(output) != 2:
        raise TypeError(f"expected demultiplexed container exec output, got {type(output)}")
    stdout, stderr = output
    if stdout is not None and not isinstance(stdout, bytes):
        raise TypeError(f"expected container exec stdout bytes, got {type(stdout)}")
    if stderr is not None and not isinstance(stderr, bytes):
        raise TypeError(f"expected container exec stderr bytes, got {type(stderr)}")
    stdout = stdout or b""
    stderr = stderr or b""
    if exit_code != 0:
        detail = (stderr or stdout).decode("utf-8", "replace").strip()
        raise RuntimeError(f"failed to {action}: {detail or f'exit code {exit_code}'}")
    return stdout


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
        raise _ContainerNotRunning(f"container {container.name} did not reach running state")
