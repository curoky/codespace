"""Resolved container specifications and Podman runtime primitives."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Collection, Iterator, Mapping, Sequence
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
_SECRET_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")
_VOLUME_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")
RESOURCE_DATA_PLACEHOLDER = "${RESOURCE_DATA}"


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


def _volume_source(value: str) -> str:
    if "$" not in value:
        return _absolute_path(value)
    if value == RESOURCE_DATA_PLACEHOLDER:
        return value
    prefix = f"{RESOURCE_DATA_PLACEHOLDER}/"
    if not value.startswith(prefix):
        raise ValueError(f"only {RESOURCE_DATA_PLACEHOLDER} may be used in volume sources")
    relative = value.removeprefix(prefix)
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or ".." in path.parts or str(path) != relative:
        raise ValueError(f"path below {RESOURCE_DATA_PLACEHOLDER} must be normalized")
    return value


def _secret_name(value: str) -> str:
    if not _SECRET_NAME_RE.fullmatch(value):
        raise ValueError("must be a valid Compose secret name")
    return value


def _volume_name(value: str) -> str:
    if not _VOLUME_NAME_RE.fullmatch(value):
        raise ValueError("must be a valid named volume")
    return value


def _host_ip(value: str) -> str:
    address = ip_address(value)
    if not address.is_loopback:
        raise ValueError("must be a loopback address")
    return str(address)


type NonBlankString = Annotated[str, AfterValidator(_not_blank)]
type AbsolutePath = Annotated[str, AfterValidator(_absolute_path)]
type SecretName = Annotated[str, AfterValidator(_secret_name)]
type SecretId = Annotated[str, Field(pattern=r"^\d+$")]
type ImagePlatform = Literal["linux/amd64", "linux/arm64"]
type PullPolicy = Literal["always", "missing", "never"]
type RestartPolicy = Literal["no", "always", "on-failure", "unless-stopped"]


class UlimitSpec(BaseModel):
    """Soft and hard limits for one named resource."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    soft: StrictInt
    hard: StrictInt


class VolumeSpec(BaseModel):
    """One normalized Compose mount: a Host bind or a named Podman volume."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["bind", "volume"]
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
        source = parts[0]
        # A leading '/' or the ${RESOURCE_DATA} placeholder marks a Host bind;
        # anything else is a named Podman volume.
        is_bind = source.startswith("/") or "$" in source
        return {
            "type": "bind" if is_bind else "volume",
            "source": source,
            "target": parts[1],
            "read_only": len(parts) == 3 and parts[2] == "ro",
        }

    @model_validator(mode="after")
    def _validate_source(self) -> Self:
        if self.type == "bind":
            _volume_source(self.source)
        else:
            _volume_name(self.source)
        return self

    def mount(self) -> dict[str, object]:
        """Produce a Podman mount; bind sources must resolve to absolute paths."""
        source = self.source if self.type == "volume" else _absolute_path(self.source)
        return {
            "type": self.type,
            "source": source,
            "target": self.target,
            "read_only": self.read_only,
        }

    @property
    def uses_resource_data(self) -> bool:
        return self.type == "bind" and (
            self.source == RESOURCE_DATA_PLACEHOLDER
            or self.source.startswith(f"{RESOURCE_DATA_PLACEHOLDER}/")
        )

    def resolve_data_path(self, data_path: str) -> Self:
        source = self.source
        if self.uses_resource_data:
            root = _absolute_path(data_path)
            relative = self.source.removeprefix(RESOURCE_DATA_PLACEHOLDER).removeprefix("/")
            source = root if not relative else f"{root}/{relative}"
        return self.model_copy(update={"source": source})


class SecretSpec(BaseModel):
    """Supported subset of Compose service secret long syntax."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: SecretName
    target: AbsolutePath | None = None
    uid: SecretId | None = None
    gid: SecretId | None = None
    mode: StrictInt = Field(default=0o444, ge=0, le=0o777)


class PortSpec(BaseModel):
    """Loopback-only subset of Compose service port long syntax."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: StrictInt = Field(ge=1, le=65535)
    published: StrictInt = Field(ge=1, le=65535)
    host_ip: Annotated[str, AfterValidator(_host_ip)]
    protocol: Literal["tcp", "udp"] = "tcp"


def _unique_volumes(volumes: list[VolumeSpec]) -> list[VolumeSpec]:
    targets = [volume.target for volume in volumes]
    if len(targets) != len(set(targets)):
        raise ValueError("volume targets must be unique")
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


type ContainerVolumes = Annotated[list[VolumeSpec], AfterValidator(_unique_volumes)]
type ContainerPorts = Annotated[list[PortSpec], AfterValidator(_unique_ports)]


class ContainerSpec(BaseModel):
    """Resolved supported subset of a Compose service."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    image: NonBlankString
    platform: ImagePlatform | None = None
    pull_policy: PullPolicy = "missing"
    network_mode: NonBlankString = "bridge"
    restart: RestartPolicy = "no"
    privileged: bool = False
    cap_add: list[NonBlankString] = Field(default_factory=list)
    security_opt: list[NonBlankString] = Field(default_factory=list)
    ipc: NonBlankString | None = None
    pids_limit: StrictInt | None = None
    ulimits: dict[NonBlankString, UlimitSpec] = Field(default_factory=dict)
    volumes: ContainerVolumes = Field(default_factory=list)
    environment: dict[NonBlankString, str] = Field(default_factory=dict)
    secrets: list[SecretSpec] = Field(default_factory=list)
    devices: list[NonBlankString] = Field(default_factory=list)
    ports: ContainerPorts = Field(default_factory=list)
    shm_size: NonBlankString | None = None

    def resolve_data_path(self, data_path: str) -> Self:
        return self.model_copy(
            update={"volumes": [volume.resolve_data_path(data_path) for volume in self.volumes]}
        )

    def data_directories(self, data_path: str) -> list[str]:
        root = PurePosixPath(data_path)
        return [
            volume.source
            for volume in self.resolve_data_path(data_path).volumes
            if PurePosixPath(volume.source).is_relative_to(root)
        ]

    def to_podman_options(
        self,
        client: PodmanClient,
        *,
        random_tcp_ports: Collection[int] = (),
    ) -> dict[str, Any]:
        """Translate the resolved Compose service to podman-py create options."""
        bind_mounts = [volume.mount() for volume in self.volumes if volume.type == "bind"]
        named_volumes = {
            volume.source: {
                "bind": volume.target,
                "mode": "ro" if volume.read_only else "rw",
            }
            for volume in self.volumes
            if volume.type == "volume"
        }
        ports: dict[str, tuple[str, int]] = {
            f"{port.target}/{port.protocol}": (port.host_ip, port.published) for port in self.ports
        }
        for target in random_tcp_ports:
            ports.setdefault(f"{target}/tcp", ("127.0.0.1", 0))
        options: dict[str, Any] = {
            "network_mode": self.network_mode,
            "restart_policy": {"Name": self.restart},
            "privileged": self.privileged,
            "cap_add": self.cap_add,
            "security_opt": self.security_opt,
            "ulimits": [
                {"Name": resource, "Soft": limit.soft, "Hard": limit.hard}
                for resource, limit in self.ulimits.items()
            ],
            "environment": self.environment,
            "devices": self.devices,
            "ports": ports,
            "mounts": bind_mounts,
            "volumes": named_volumes,
        }
        if self.platform is not None:
            options["platform"] = self.platform
        if self.pids_limit is not None:
            options["pids_limit"] = self.pids_limit
        if self.shm_size is not None:
            options["shm_size"] = self.shm_size
        if self.ipc is not None:
            options["ipc_mode"] = self.ipc
        secret_mounts = _resolve_secrets(client, self.secrets)
        if secret_mounts:
            options["secrets"] = secret_mounts
        return options


def create_container(
    client: PodmanClient,
    *,
    name: str,
    spec: ContainerSpec,
    labels: Mapping[str, str],
    random_tcp_ports: Collection[int] = (),
) -> Container:
    """Create a detached container from one resolved Compose service."""
    options = {
        **spec.to_podman_options(client, random_tcp_ports=random_tcp_ports),
        "name": name,
        "labels": dict(labels),
    }
    return run_container(client, spec.image, options)


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


def pull_image(
    client: PodmanClient,
    image: str,
    platform: ImagePlatform | None,
    policy: PullPolicy = "always",
) -> None:
    """Pull an image while surfacing errors from the streaming API."""
    kwargs: dict[str, Any] = {"stream": True, "decode": True, "policy": policy}
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


def published_tcp_endpoint(container: Container, target_port: int) -> tuple[str, int] | None:
    bindings = container.attrs.get("NetworkSettings", {}).get("Ports", {}).get(f"{target_port}/tcp")
    if bindings is None:
        return None
    if not isinstance(bindings, list) or len(bindings) != 1:
        raise RuntimeError(
            f"container port {target_port}/tcp must have exactly one Host publication"
        )
    binding = bindings[0]
    if not isinstance(binding, dict):
        raise RuntimeError(f"container port {target_port}/tcp has invalid publication metadata")
    host_ip = binding.get("HostIp")
    host_port = binding.get("HostPort")
    if not isinstance(host_ip, str) or not isinstance(host_port, str) or not host_port.isdigit():
        raise RuntimeError(f"container port {target_port}/tcp has invalid publication metadata")
    return _host_ip(host_ip), int(host_port)


class _ContainerNotRunning(Exception):
    pass


def wait_running(container: Container) -> None:
    try:
        _reload_until_running(container)
    except _ContainerNotRunning:
        container.reload()
        state = container.attrs["State"]
        details = [f"status={container.status}"]
        if isinstance(state, dict):
            exit_code = state.get("ExitCode")
            if exit_code is not None:
                details.append(f"exit_code={exit_code}")
            if state.get("OOMKilled"):
                details.append("oom_killed=true")
            if error := state.get("Error"):
                details.append(f"error={error}")
        logs = container_logs(container).strip()
        suffix = f": {logs}" if logs else ""
        raise RuntimeError(
            f"container {container.name} did not reach running state ({', '.join(details)}){suffix}"
        ) from None


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
