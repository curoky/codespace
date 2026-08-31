"""Codespace container semantics layered over the Podman engine.

This module owns the control-plane-specific translation: reserved environment
injection (``SSHD_PORT``/``SSHD_BIND``), the reserved workspace mount, default
secret ownership (``5230:5230``, ``0o400``) and canonical labels. The reusable
container primitives live in :mod:`controller.runtime.engine`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from podman import PodmanClient
from podman.domain.containers import Container

from controller.config import DeploymentSpec, EnvironmentSpec
from controller.models import (
    CACHE_MOUNT,
    CONTAINER_GID,
    CONTAINER_UID,
    DEPLOYMENT_DATA_PLACEHOLDER,
    UPLOAD_MOUNT,
    WORKSPACE_CIPHER_MOUNT,
    WORKSPACE_CRYPT_SECRET,
    WORKSPACE_CRYPT_SECRET_ENV,
    WORKSPACE_MOUNT,
    Environment,
    HostRoots,
    ImagePlatform,
)
from controller.runtime import engine
from controller.runtime.compose import Secret, ServiceSpec, Volume
from controller.runtime.engine import (
    CommandResult,
    container_logs,
    execute,
    execute_checked,
    pull_image,
    remove_container,
    wait_running,
)

__all__ = [
    "CommandResult",
    "container_logs",
    "create_container",
    "create_deployment_container",
    "execute",
    "execute_checked",
    "pull_image",
    "purge_workspace",
    "remove_container",
    "remove_workspace",
    "wait_running",
]


def create_container(
    client: PodmanClient,
    spec: EnvironmentSpec,
    roots: HostRoots,
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
    # Encrypted workspaces bind the host instance dir to the gocryptfs cipher root
    # and inject the fixed WORKSPACE_CRYPT_KEY (like the sidecar's atuin_db_uri);
    # the image mounts the decrypted /workspace at boot. Plaintext workspaces bind
    # the host dir straight to /workspace and inject nothing. /upload and /cache
    # always bind their own plaintext host roots per instance.
    encrypt = spec.workspace.encrypt_workspace
    if encrypt:
        _require_secret_exists(client, WORKSPACE_CRYPT_SECRET)
        secret_env[WORKSPACE_CRYPT_SECRET_ENV] = WORKSPACE_CRYPT_SECRET
    env_collisions = sorted(environment.keys() & secret_env.keys())
    if env_collisions:
        raise ValueError(f"container.secrets env target also set in environment: {env_collisions}")

    mounts: list[dict[str, object]] = [
        {
            "type": "bind",
            "source": spec.instance_path(roots.workspace),
            "target": WORKSPACE_CIPHER_MOUNT if encrypt else WORKSPACE_MOUNT,
        },
        {
            "type": "bind",
            "source": spec.instance_path(roots.upload),
            "target": UPLOAD_MOUNT,
        },
        {
            "type": "bind",
            "source": spec.instance_path(roots.cache),
            "target": CACHE_MOUNT,
        },
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
    return engine.run_container(client, spec.image, run_options)


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
    """Assemble the podman-py run options shared by environments and deployments.

    Callers layer their own specifics on top of the returned dict (an
    environment adds ``platform``; a deployment passes ``restart_policy``); this
    only builds the container-block fields both share.
    """
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
    if not engine.secret_exists(client, name):
        raise RuntimeError(
            f"Podman secret {name!r} is not registered on the host; "
            "create it with `podman secret create` before starting the environment"
        )


def create_deployment_container(
    client: PodmanClient,
    spec: DeploymentSpec,
    data_root: str,
) -> Container:
    """Create and start a self-contained host-level deployment container.

    Unlike an environment, a deployment has no SSH projection, workspace mount or
    git checkout: it runs the image as-is with the resolved container block and a
    restart policy so it survives host reboots. A ``${DEPLOYMENT_DATA}`` volume
    source is rewritten to the deployment's managed data path below ``data_root``.
    """
    options = spec.container
    data_path = spec.data_path(data_root)
    environment = dict(options.environment or {})
    ports: dict[str, object] = {}
    if options.is_bridge:
        for local, remote in spec.published_ports:
            ports[f"{remote}/tcp"] = local

    secret_mounts, secret_env = _resolve_secrets(client, options.secrets or [])
    env_collisions = sorted(environment.keys() & secret_env.keys())
    if env_collisions:
        raise ValueError(f"container.secrets env target also set in environment: {env_collisions}")

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
    return engine.run_container(client, spec.image, run_options)


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
    roots: HostRoots,
) -> None:
    """Stop an environment and remove its workspace, upload and cache dirs."""
    container.stop(timeout=10, ignore=True)
    platform = None if environment.platform == "native" else environment.platform
    suffix = f"/{environment.workspace}/{environment.instance}"
    for root in (roots.workspace, roots.upload, roots.cache):
        remove_workspace(
            client,
            environment.image,
            root,
            f"{root}{suffix}",
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
    engine.remove_dir_with_helper(client, image, workspace_root, target, platform=platform)
