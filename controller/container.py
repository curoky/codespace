"""Codespace container semantics plus the Podman image/container primitives.

Owns the control-plane translation (managed labels, reserved env injection,
reserved workspace mounts, default secret ownership) and the reusable Podman
primitives (image pull, run, logs, removal, directory-removal helper) it drives.
"""

from __future__ import annotations

import posixpath
from collections.abc import Iterator, Mapping
from typing import Any, cast

from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import PodmanError
from tenacity import retry, retry_if_exception_type, stop_after_delay, wait_fixed

from controller.compose import Secret, ServiceSpec, Volume
from controller.config import DeploymentSpec, EnvironmentSpec
from controller.models import (
    CACHE_MOUNT,
    CONTAINER_GID,
    CONTAINER_UID,
    CONTROL_MOUNT,
    DEPLOYMENT_DATA_PLACEHOLDER,
    UPLOAD_MOUNT,
    WORKSPACE_CIPHER_MOUNT,
    WORKSPACE_CLONE_PATH_ENV,
    WORKSPACE_CLONE_URL_ENV,
    WORKSPACE_CRYPT_SECRET,
    WORKSPACE_CRYPT_SECRET_ENV,
    WORKSPACE_MOUNT,
    WORKSPACE_OPEN_PATH_ENV,
    WORKSPACE_TYPE_ENV,
    Environment,
    ImagePlatform,
    InstancePaths,
    git_host,
)

_READY_TIMEOUT = 30.0
_READY_INTERVAL = 0.25
_PULL_TIMEOUT = 15 * 60.0
_LOG_TAIL = 2000


def create_container(
    client: PodmanClient,
    spec: EnvironmentSpec,
    paths: InstancePaths,
    host_environment: Mapping[str, str] | None = None,
) -> Container:
    """Create and start a configured development container."""
    options = spec.container
    environment = {
        **(host_environment or {}),
        **(options.environment or {}),
        WORKSPACE_TYPE_ENV: spec.workspace.type,
        WORKSPACE_CLONE_PATH_ENV: spec.clone_path,
        WORKSPACE_OPEN_PATH_ENV: spec.open_path,
        "SSHD_PORT": str(spec.ssh_port),
    }
    if spec.workspace.repo is not None and spec.workspace.provider is not None:
        environment[WORKSPACE_CLONE_URL_ENV] = (
            f"git@{git_host(spec.workspace.provider)}:{spec.workspace.repo}.git"
        )
    elif spec.workspace.git_url is not None:
        environment[WORKSPACE_CLONE_URL_ENV] = spec.workspace.git_url
    ports: dict[str, object] = {}
    if options.is_bridge:
        environment["SSHD_BIND"] = "0.0.0.0"  # noqa: S104
        ports[f"{spec.ssh_port}/tcp"] = ("127.0.0.1", spec.ssh_port)
        for local, remote in spec.published_ports:
            ports[f"{remote}/tcp"] = local

    secret_mounts, secret_env = _resolve_secrets(client, options.secrets or [])
    # Encrypted workspaces bind the host instance dir to the gocryptfs cipher
    # root and inject the fixed WORKSPACE_CRYPT_KEY; the image mounts the
    # decrypted /workspace at boot. Plaintext workspaces bind straight to
    # /workspace. /upload and /cache always bind sibling plaintext directories;
    # IDE state stays below cache and is also mounted at each tool's home path.
    encrypt = spec.workspace.encrypt_workspace
    if encrypt:
        _require_secret_exists(client, WORKSPACE_CRYPT_SECRET)
        secret_env[WORKSPACE_CRYPT_SECRET_ENV] = WORKSPACE_CRYPT_SECRET

    mounts: list[dict[str, object]] = [
        {
            "type": "bind",
            "source": paths.workspace,
            "target": WORKSPACE_CIPHER_MOUNT if encrypt else WORKSPACE_MOUNT,
        },
        {"type": "bind", "source": paths.upload, "target": UPLOAD_MOUNT},
        {"type": "bind", "source": paths.cache, "target": CACHE_MOUNT},
    ]
    mounts.extend(
        {"type": "bind", "source": source, "target": target}
        for source, target in paths.home_cache_mounts
    )
    mounts.append({"type": "bind", "source": paths.control, "target": CONTROL_MOUNT})
    mounts.extend(
        {
            "type": "bind",
            "source": volume.source,
            "target": volume.target,
            "read_only": volume.read_only,
        }
        for volume in options.volumes or []
    )

    run_options = _build_run_options(
        name=spec.identity,
        options=options,
        environment=environment,
        ports=ports,
        labels=spec.labels(),
        mounts=mounts,
        secret_mounts=secret_mounts,
        secret_env=secret_env,
    )
    run_options["platform"] = spec.platform
    return run_container(client, spec.image, run_options)


def _build_run_options(
    *,
    name: str,
    options: ServiceSpec,
    environment: dict[str, str],
    ports: dict[str, object],
    labels: dict[str, str],
    mounts: list[dict[str, object]],
    secret_mounts: list[dict[str, object]],
    secret_env: dict[str, str],
    restart_policy: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Assemble the podman-py run options shared by environments and deployments."""
    run_options: dict[str, Any] = {
        "name": name,
        "network_mode": options.network_mode,
        "cap_add": options.cap_add or [],
        "security_opt": options.security_opt or [],
        "ulimits": [
            {"Name": limit_name, "Soft": limit.soft, "Hard": limit.hard}
            for limit_name, limit in (options.ulimits or {}).items()
        ],
        "environment": environment,
        "devices": options.devices or [],
        "ports": ports,
        "labels": labels,
        "mounts": mounts,
    }
    if restart_policy is not None:
        run_options["restart_policy"] = restart_policy
    if options.pids_limit is not None:
        run_options["pids_limit"] = options.pids_limit
    if options.shm_size is not None:
        run_options["shm_size"] = options.shm_size
    if options.ipc is not None:
        run_options["ipc_mode"] = options.ipc
    if secret_mounts:
        run_options["secrets"] = secret_mounts
    if secret_env:
        run_options["secret_env"] = secret_env
    return run_options


def _resolve_secrets(
    client: PodmanClient,
    secrets: list[Secret],
) -> tuple[list[dict[str, object]], dict[str, str]]:
    """Split configured secrets into podman-py mount and env parameters.

    Each ``source`` must already be registered on the host; missing secrets fail
    fast. Mount secrets default to the development user (``5230:5230``, ``0o400``).
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


def create_deployment_container(
    client: PodmanClient,
    spec: DeploymentSpec,
    data_path: str,
) -> Container:
    """Create and start a self-contained host-level deployment container.

    Runs the image as-is with the resolved container block and an
    ``unless-stopped`` restart policy. A ``${DEPLOYMENT_DATA}`` volume source is
    rewritten to ``data_path``.
    """
    options = spec.container
    environment = dict(options.environment or {})
    ports: dict[str, object] = {}
    if options.is_bridge:
        for local, remote in spec.published_ports:
            ports[f"{remote}/tcp"] = local

    secret_mounts, secret_env = _resolve_secrets(client, options.secrets or [])
    mounts = [_deployment_mount(volume, data_path) for volume in options.volumes or []]

    run_options = _build_run_options(
        name=spec.identity,
        options=options,
        environment=environment,
        ports=ports,
        labels=spec.labels(),
        mounts=mounts,
        secret_mounts=secret_mounts,
        secret_env=secret_env,
        restart_policy={"Name": "unless-stopped"},
    )
    return run_container(client, spec.image, run_options)


def _deployment_mount(volume: Volume, data_path: str) -> dict[str, object]:
    """Translate one deployment volume, resolving the managed data placeholder."""
    source = volume.source
    if source == DEPLOYMENT_DATA_PLACEHOLDER:
        source = data_path
    elif source.startswith("${"):
        raise ValueError(
            f"deployment volume source {volume.source!r} uses an unknown placeholder; "
            f"only {DEPLOYMENT_DATA_PLACEHOLDER} is supported"
        )
    return {
        "type": "bind",
        "source": source,
        "target": volume.target,
        "read_only": volume.read_only,
    }


def purge_workspace(
    client: PodmanClient,
    container: Container,
    environment: Environment,
    paths: InstancePaths,
) -> None:
    """Stop an environment and remove its complete data directory."""
    container.stop(timeout=10, ignore=True)
    platform = None if environment.platform == "native" else environment.platform
    remove_data_directory(
        client,
        environment.image,
        paths.workspaces_root,
        paths.root,
        platform=platform,
    )


# --- Podman primitives (no control-plane knowledge below this line) ---


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
    """Create, start and await a detached container from resolved run options."""
    created = client.containers.run(image, detach=True, **run_options)
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
    """Remove one directory strictly below ``data_root`` with a root helper container."""
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
            text = raw.decode("utf-8", "replace").strip()
            raise RuntimeError(f"failed to remove {target!r} ({exit_code}): {text}")
    finally:
        helper.remove(force=True)


def remove_container(container: Container) -> None:
    container.remove(force=True)


def container_logs(container: Container) -> str:
    """Return the container's most recent combined stdout and stderr logs."""
    result = container.logs(
        stdout=True,
        stderr=True,
        stream=False,
        timestamps=True,
        tail=_LOG_TAIL,
    )
    raw = result if isinstance(result, bytes) else b"".join(result)
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else ""


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
