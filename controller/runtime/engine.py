"""Provider-neutral Podman image and container primitives.

This module holds no control-plane knowledge: it exposes reusable container
engine operations (image pull, container run, logs, removal and a helper container
to delete a directory) that callers drive with already-resolved parameters.
Codespace-specific semantics (labels, workspace mounts, reserved environment keys,
default ownership) live in the business layer.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterator
from typing import Any, cast

from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import PodmanError
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_fixed

_READY_TIMEOUT = 30.0
_READY_INTERVAL = 0.25
_PULL_TIMEOUT = 15 * 60.0
_LOG_TAIL = 2000

type ImagePlatform = str


class _ContainerNotRunning(Exception):
    pass


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


def run_container(client: PodmanClient, image: str, run_options: dict[str, Any]) -> Container:
    """Create, start and await a detached container from resolved run options.

    ``run_options`` is forwarded verbatim to ``client.containers.run``; the
    caller owns the full translation from higher-level configuration into
    podman-py keyword arguments.
    """
    created = client.containers.run(image, detach=True, **run_options)
    if not isinstance(created, Container):
        raise TypeError(f"expected Container, got {type(created)}")
    wait_running(created)
    return created


def secret_exists(client: PodmanClient, name: str) -> bool:
    """Return whether a Podman secret is registered on the host."""
    return bool(client.secrets.exists(name))


def remove_dir_with_helper(
    client: PodmanClient,
    image: str,
    root: str,
    target: str,
    *,
    platform: ImagePlatform | None = None,
) -> None:
    """Remove one directory strictly below ``root`` with a root helper container."""
    normalized_root = posixpath.normpath(root)
    normalized_target = posixpath.normpath(target)
    if (
        not normalized_root.startswith("/")
        or not normalized_target.startswith("/")
        or posixpath.commonpath((normalized_root, normalized_target)) != normalized_root
        or normalized_target == normalized_root
    ):
        raise RuntimeError(f"refusing to remove {target!r} outside root {root!r}")
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
        raise RuntimeError("expected a detached directory-removal container")
    try:
        exit_code = helper.wait()
        if exit_code not in (0, None):
            logs = helper.logs(stdout=True, stderr=True)
            raw = logs if isinstance(logs, bytes) else b"".join(logs)
            text = raw.decode("utf-8", "replace").strip()
            raise RuntimeError(f"failed to remove {target!r} ({exit_code}): {text}")
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
