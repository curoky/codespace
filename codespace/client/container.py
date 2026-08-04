"""Podman image, container and exec primitives."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, cast

from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import PodmanError
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_fixed

from codespace.client.models import (
    WORKSPACE_MOUNT,
    Environment,
    EnvironmentSpec,
    ImagePlatform,
    environment_labels,
)

_READY_TIMEOUT = 30.0
_READY_INTERVAL = 0.25


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
    events = cast("Iterator[dict[str, str]]", client.images.pull(image, **kwargs))
    for event in events:
        error = event.get("error") if isinstance(event, dict) else None
        if error:
            raise PodmanError(f"failed to pull {image}: {error}")


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
        platform=spec.project.platform,
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
    helper = client.containers.run(
        environment.image,
        name=None,
        entrypoint=["/bin/rm"],
        command=["-rf", "--", target],
        detach=True,
        platform=platform,
        user="0",
        security_opt=["disable"],
        mounts=[{"type": "bind", "source": workspace_root, "target": workspace_root}],
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


def ensure_running(container: Container) -> None:
    """Start a stopped container before creating exec sessions."""
    container.reload()
    if container.status == "running":
        return
    container.start()
    wait_running(container)


def execute(container: Container, command: list[str], *, user: str) -> CommandResult:
    """Execute a command with separate stdout and stderr streams."""
    exit_code, output = container.exec_run(command, user=user, demux=True)
    stdout_raw, stderr_raw = output if isinstance(output, tuple) else (output, None)
    stdout = _decode_stream(stdout_raw)
    stderr = _decode_stream(stderr_raw)
    if exit_code is None:
        raise RuntimeError(f"exec {command!r} returned no exit code: {stderr or stdout}")
    return CommandResult(code=exit_code, stdout=stdout, stderr=stderr)


def execute_checked(container: Container, command: list[str], *, user: str) -> None:
    result = execute(container, command, user=user)
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
