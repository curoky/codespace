"""Podman image, container and exec primitives."""

from __future__ import annotations

import json
import posixpath
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, cast

from podman import PodmanClient
from podman.api.output_utils import demux_output
from podman.domain.containers import Container
from podman.errors import PodmanError
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_fixed

from controller.compose import Secret
from controller.models import (
    CONTAINER_GID,
    CONTAINER_UID,
    WORKSPACE_MOUNT,
    Environment,
    EnvironmentSpec,
    ImagePlatform,
    environment_labels,
)

_READY_TIMEOUT = 30.0
_READY_INTERVAL = 0.25
_EXEC_TIMEOUT = 60.0
_PULL_TIMEOUT = 15 * 60.0
_LOG_TAIL = 2000


class _ContainerNotRunning(Exception):
    pass


@dataclass(frozen=True, slots=True)
class CommandResult:
    code: int
    stdout: str
    stderr: str


def pull_image(client: PodmanClient, image: str, platform: ImagePlatform | None) -> None:
    """Pull an image while surfacing stream errors."""
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
        pull_client.close()


def create_container(
    client: PodmanClient,
    spec: EnvironmentSpec,
    workspace_root: str,
    host_environment: Mapping[str, str] | None = None,
) -> Container:
    """Create and start a configured development container."""
    options = spec.container
    configured_environment = options.environment or {}
    inherited_environment = host_environment or {}
    collisions = sorted(inherited_environment.keys() & configured_environment.keys())
    if collisions:
        raise ValueError(
            f"host environment variables also set in container.environment: {collisions}"
        )
    environment = {
        **inherited_environment,
        **configured_environment,
        "SSHD_PORT": str(spec.ssh_port),
    }
    ports: dict[str, object] = {}
    if options.is_bridge:
        environment["SSHD_BIND"] = "0.0.0.0"  # noqa: S104
        ports[f"{spec.ssh_port}/tcp"] = ("127.0.0.1", spec.ssh_port)
        for local, remote in spec.published_ports:
            ports[f"{remote}/tcp"] = local

    secret_mounts, secret_env = _resolve_secrets(client, options.secrets or [])
    env_collisions = sorted(environment.keys() & secret_env.keys())
    if env_collisions:
        raise ValueError(f"container.secrets env target also set in environment: {env_collisions}")

    mounts: list[dict[str, object]] = [
        {
            "type": "bind",
            "source": spec.workspace_path(workspace_root),
            "target": WORKSPACE_MOUNT,
        }
    ]
    mounts.extend(
        {
            "type": "bind",
            "source": volume.source,
            "target": volume.target,
            "read_only": volume.read_only,
        }
        for volume in options.volumes or []
    )

    run_kwargs: dict[str, Any] = {}
    if options.pids_limit is not None:
        run_kwargs["pids_limit"] = options.pids_limit
    if options.shm_size is not None:
        run_kwargs["shm_size"] = options.shm_size
    if secret_mounts:
        run_kwargs["secrets"] = secret_mounts
    if secret_env:
        run_kwargs["secret_env"] = secret_env
    created = client.containers.run(
        spec.image,
        name=spec.identity,
        detach=True,
        network_mode=options.network_mode,
        cap_add=options.cap_add or [],
        security_opt=options.security_opt or [],
        ulimits=[
            {"Name": name, "Soft": limit.soft, "Hard": limit.hard}
            for name, limit in (options.ulimits or {}).items()
        ],
        environment=environment,
        platform=spec.platform,
        devices=options.devices or [],
        ports=ports,
        labels=environment_labels(spec),
        mounts=mounts,
        **run_kwargs,
    )
    if not isinstance(created, Container):
        raise TypeError(f"expected Container, got {type(created)}")
    wait_running(created)
    return created


def _resolve_secrets(
    client: PodmanClient,
    secrets: list[Secret],
) -> tuple[list[dict[str, object]], dict[str, str]]:
    """Split configured secrets into podman-py mount and env parameters.

    The control plane only references secrets by name: each ``source`` must
    already be registered on the host with ``podman secret create``. Missing
    secrets fail fast before the container is created. Mount secrets default to
    the development user (``5230:5230``) with mode ``0o400`` so only ``x`` can
    read the file.
    """
    mounts: list[dict[str, object]] = []
    env: dict[str, str] = {}
    for secret in secrets:
        _require_secret_exists(client, secret.source)
        if secret.mode == "env":
            if secret.target is None:
                raise ValueError(f"env secret {secret.source!r} has no target")
            env[secret.target] = secret.source
            continue
        mount: dict[str, object] = {
            "source": secret.source,
            "uid": secret.uid if secret.uid is not None else CONTAINER_UID,
            "gid": secret.gid if secret.gid is not None else CONTAINER_GID,
            "mode": secret.file_mode if secret.file_mode is not None else 0o400,
        }
        if secret.target is not None:
            mount["target"] = secret.target
        mounts.append(mount)
    return mounts, env


def _require_secret_exists(client: PodmanClient, name: str) -> None:
    if not client.secrets.exists(name):
        raise RuntimeError(
            f"Podman secret {name!r} is not registered on the host; "
            "create it with `podman secret create` before starting the environment"
        )


def purge_workspace(
    client: PodmanClient,
    container: Container,
    environment: Environment,
    workspace_root: str,
) -> None:
    """Stop an environment and remove its workspace with a helper container."""
    container.stop(timeout=10, ignore=True)
    target = f"{workspace_root}/{environment.project}/{environment.instance}"
    platform = None if environment.platform == "native" else environment.platform
    remove_workspace(
        client,
        environment.image,
        workspace_root,
        target,
        platform=platform,
    )


def remove_workspace(
    client: PodmanClient,
    image: str,
    workspace_root: str,
    target: str,
    *,
    platform: ImagePlatform | None = None,
) -> None:
    """Remove one workspace below the mounted root with a root helper container."""
    normalized_root = posixpath.normpath(workspace_root)
    normalized_target = posixpath.normpath(target)
    if (
        not normalized_root.startswith("/")
        or not normalized_target.startswith("/")
        or posixpath.commonpath((normalized_root, normalized_target)) != normalized_root
        or normalized_target == normalized_root
    ):
        raise RuntimeError(
            f"refusing to remove workspace {target!r} outside root {workspace_root!r}"
        )
    helper = client.containers.run(
        image,
        name=None,
        entrypoint=["/bin/rm"],
        command=["-rf", "--", normalized_target],
        detach=True,
        platform=platform,
        user="0",
        security_opt=["disable"],
        mounts=[
            {
                "type": "bind",
                "source": normalized_root,
                "target": normalized_root,
            }
        ],
    )
    if not isinstance(helper, Container):
        raise RuntimeError("expected a detached workspace-removal container")
    try:
        exit_code = helper.wait()
        if exit_code not in (0, None):
            logs = helper.logs(stdout=True, stderr=True)
            raw = logs if isinstance(logs, bytes) else b"".join(logs)
            text = raw.decode("utf-8", "replace").strip()
            raise RuntimeError(f"failed to remove workspace {target!r} ({exit_code}): {text}")
    finally:
        helper.remove(force=True)


def remove_container(container: Container) -> None:
    container.remove(force=True)


def container_logs(container: Container, *, tail: int = _LOG_TAIL) -> str:
    """Return the container's most recent combined stdout and stderr logs."""
    result = container.logs(
        stdout=True,
        stderr=True,
        stream=False,
        timestamps=True,
        tail=tail,
    )
    raw = result if isinstance(result, bytes) else b"".join(result)
    return _decode_stream(raw)


def execute(
    container: Container,
    command: list[str],
    *,
    user: str,
    timeout: float = _EXEC_TIMEOUT,
) -> CommandResult:
    """Execute a command with separate stdout and stderr streams."""
    client = container.client
    if client is None:
        raise RuntimeError("container has no Podman API client")
    identity = str(container.id or container.name)
    response = client.post(
        f"/containers/{identity}/exec",
        data=json.dumps(
            {
                "AttachStderr": True,
                "AttachStdin": False,
                "AttachStdout": True,
                "Cmd": command,
                "Env": None,
                "Privileged": False,
                "Tty": False,
                "WorkingDir": None,
                "User": user,
            }
        ),
    )
    response.raise_for_status()
    payload = response.json()
    exec_id = payload.get("Id") if isinstance(payload, dict) else None
    if not isinstance(exec_id, str) or not exec_id:
        raise RuntimeError(f"exec {command!r} returned no exec ID")

    started = client.post(
        f"/exec/{exec_id}/start",
        data=json.dumps({"Detach": False, "Tty": False}),
        timeout=timeout,
    )
    started.raise_for_status()
    inspected = client.get(f"/exec/{exec_id}/json")
    inspected.raise_for_status()
    inspected_payload = inspected.json()
    exit_code = inspected_payload.get("ExitCode") if isinstance(inspected_payload, dict) else None
    stdout_raw, stderr_raw = demux_output(started.content)
    stdout = _decode_stream(stdout_raw)
    stderr = _decode_stream(stderr_raw)
    if not isinstance(exit_code, int):
        raise RuntimeError(f"exec {command!r} returned no exit code: {stderr or stdout}")
    return CommandResult(code=exit_code, stdout=stdout, stderr=stderr)


def execute_checked(
    container: Container,
    command: list[str],
    *,
    user: str,
    timeout: float = _EXEC_TIMEOUT,
) -> None:
    result = execute(container, command, user=user, timeout=timeout)
    if result.code != 0:
        raise RuntimeError(
            f"exec {command!r} failed ({result.code}): {result.stderr or result.stdout}"
        )


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


def _decode_stream(raw: bytes | None) -> str:
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else ""
