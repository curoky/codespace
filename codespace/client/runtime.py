"""Remote Podman inventory and development-container lifecycle primitives."""

from __future__ import annotations

import io
import tarfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import NotFound, PodmanError

from codespace.client.config import Config, ContainerConfig, ProjectConfig
from codespace.client.models import (
    CONTAINER_USER,
    LABEL_IMAGE,
    LABEL_INSTANCE,
    LABEL_MANAGED,
    LABEL_PLATFORM,
    LABEL_PROJECT,
    LABEL_PROVIDER,
    LABEL_REPO,
    LABEL_SSH_PORT,
    LABEL_TYPE,
    MANDATORY_LABELS,
    REPO_RE,
    RESOURCE_ID_RE,
    WORKSPACE_MOUNT,
    Environment,
    GitProvider,
    ImagePlatform,
    PlatformSelection,
    ProjectType,
    RepoGitState,
    environment_id,
    environment_labels,
    git_host,
    platform_label,
    repo_target,
    ssh_port,
    workspace_path,
)

_READY_TIMEOUT = 30.0
_READY_INTERVAL = 0.25
# Read-side counterpart of ``environment_labels``; keep aligned with
# ``MANDATORY_LABELS`` so the write and read paths cannot drift apart.
_REQUIRED_LABELS = MANDATORY_LABELS


@dataclass(frozen=True, slots=True)
class Inventory:
    """Managed environments and corruption errors read from one host."""

    environments: list[Environment]
    errors: list[str]


@dataclass(frozen=True, slots=True)
class DeployKeypair:
    """OpenSSH deploy key material kept only in process memory."""

    private_key: str
    public_key: str


def generate_deploy_keypair() -> DeployKeypair:
    """Generate one in-memory OpenSSH ed25519 deploy keypair."""
    private_key = Ed25519PrivateKey.generate()
    private_openssh = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_openssh = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode()
    )
    return DeployKeypair(private_key=private_openssh, public_key=public_openssh)


def list_inventory(client: PodmanClient, host: str, config: Config) -> Inventory:
    """Read all managed containers on one host without hiding damaged state."""
    environments: list[Environment] = []
    errors: list[str] = []
    containers = client.containers.list(
        all=True,
        filters={"label": f"{LABEL_MANAGED}=true"},
    )
    for container in containers:
        try:
            environment = read_environment(container, host, config)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            environments.append(environment)
    return Inventory(
        environments=sorted(
            environments,
            key=lambda environment: (environment.project, environment.instance),
        ),
        errors=errors,
    )


def read_environment(container: Container, host: str, config: Config) -> Environment:
    """Validate a managed container's complete label contract."""
    name = _container_name(container)
    raw_labels = container.labels or {}
    if raw_labels.get(LABEL_MANAGED) != "true":
        raise ValueError(f"container {name} has invalid label {LABEL_MANAGED}")
    labels = {key: _required_label(raw_labels, name, key) for key in _REQUIRED_LABELS}
    project = labels[LABEL_PROJECT]
    instance = labels[LABEL_INSTANCE]
    project_type = _project_type(labels[LABEL_TYPE], name)
    image = labels[LABEL_IMAGE]
    platform = _platform(labels[LABEL_PLATFORM], name)

    if not RESOURCE_ID_RE.fullmatch(project):
        raise ValueError(f"container {name} has invalid project label {project!r}")
    if not RESOURCE_ID_RE.fullmatch(instance):
        raise ValueError(f"container {name} has invalid instance label {instance!r}")
    if project not in config.projects:
        raise ValueError(f"container {name} references unknown project {project!r}")
    configured_project = config.projects[project]
    if configured_project.host != host:
        raise ValueError(
            f"container {name} project {project!r} belongs to host "
            f"{configured_project.host!r}, not {host!r}"
        )
    if configured_project.type != project_type:
        raise ValueError(
            f"container {name} type {project_type!r} does not match project {project!r}"
        )
    repo, provider = _read_repo_labels(raw_labels, name, project_type, configured_project)
    identity = environment_id(host, project, instance)
    if name != identity:
        raise ValueError(f"container {name} must use deterministic name {identity!r}")
    try:
        port = int(labels[LABEL_SSH_PORT])
    except ValueError as exc:
        raise ValueError(
            f"container {name} has invalid SSH port label {labels[LABEL_SSH_PORT]!r}"
        ) from exc
    expected_port = ssh_port(identity)
    if port != expected_port:
        raise ValueError(f"container {name} has SSH port {port}, expected {expected_port}")

    return Environment(
        id=identity,
        host=host,
        project=project,
        instance=instance,
        type=project_type,
        repo=repo,
        provider=provider,
        image=image,
        platform=platform,
        ssh_port=port,
        container_id=container.id,
        status=container_status(container),
    )


def _read_repo_labels(
    raw_labels: dict[str, str],
    name: str,
    project_type: ProjectType,
    configured_project: ProjectConfig,
) -> tuple[str | None, GitProvider | None]:
    """Validate repo/provider labels against the resolved project type."""
    if project_type == "blank":
        if raw_labels.get(LABEL_REPO) or raw_labels.get(LABEL_PROVIDER):
            raise ValueError(f"container {name} is blank but has repo or provider label")
        return None, None
    repo = _required_label(raw_labels, name, LABEL_REPO)
    provider = _provider(_required_label(raw_labels, name, LABEL_PROVIDER), name)
    if not REPO_RE.fullmatch(repo):
        raise ValueError(f"container {name} has invalid repo label {repo!r}")
    if configured_project.repo != repo or configured_project.provider != provider:
        raise ValueError(f"container {name} labels do not match project labels")
    return repo, provider


def find_container(
    client: PodmanClient,
    host: str,
    project: str,
    instance: str,
    config: Config,
) -> Container | None:
    """Find and validate the deterministic managed container."""
    identity = environment_id(host, project, instance)
    try:
        container = client.containers.get(identity)
    except NotFound:
        return None
    environment = read_environment(container, host, config)
    if environment.project != project or environment.instance != instance:
        raise ValueError(f"container {identity} has mismatched identity labels")
    return container


def pull_image(
    client: PodmanClient,
    image: str,
    platform: ImagePlatform | None,
) -> None:
    """Pull the configured project image before any helper or container run.

    Stream the pull so the client read timeout bounds the gap between progress
    chunks instead of the whole download; large images would otherwise trip the
    per-request timeout while data is still flowing. Draining the generator also
    surfaces mid-stream errors that a non-streaming pull would swallow.
    """
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
    *,
    host: str,
    project: str,
    instance: str,
    project_type: ProjectType,
    repo: str | None,
    provider: GitProvider | None,
    image: str,
    platform: ImagePlatform | None,
    workspace_root: str,
    container: ContainerConfig,
    published_ports: list[tuple[int, int]] | None = None,
) -> Container:
    """Create the deterministic development container.

    A ``host`` network container shares the host netns so sshd on
    ``127.0.0.1:<ssh_port>`` is reachable through ProxyJump. A ``bridge``
    container gets its own netns, so sshd is told to bind ``0.0.0.0`` and the
    SSH port is published on the loopback to preserve the existing ProxyCommand
    path unchanged. Business ``published_ports`` are published on all interfaces
    so a Podman machine forwards them to the macOS host loopback.

    All non-identity run flags (``network_mode``, ``cap_add``, ``security_opt``,
    ``pids_limit``, ``ulimits``, ``devices``, extra ``volumes`` and
    ``environment``) come from ``container`` and are forwarded verbatim; the
    control plane keeps no implicit defaults for them. ``network_mode`` is
    guaranteed non-null by config validation. GPU access is expressed as a CDI
    device entry such as ``nvidia.com/gpu=all`` in ``container.devices``.
    """
    identity = environment_id(host, project, instance)
    port = ssh_port(identity)
    network_mode = container.network_mode
    bridge = container.is_bridge
    labels = environment_labels(
        project=project,
        instance=instance,
        project_type=project_type,
        repo=repo,
        provider=provider,
        image=image,
        platform=platform_label(platform),
        ssh_port=port,
    )
    # Derived keys are written last so a stray configured env key can never
    # silently override the control-plane values; config.ContainerConfig already
    # rejects the reserved keys at load time, so a collision here is impossible.
    environment = {**(container.environment or {}), "SSHD_PORT": str(port)}
    ports: dict[str, object] = {}
    if bridge:
        environment["SSHD_BIND"] = "0.0.0.0"  # noqa: S104
        # SSH stays on the VM loopback so the ProxyCommand path is unchanged and
        # sshd is never exposed through the machine's user-facing port forwarder.
        ports[f"{port}/tcp"] = ("127.0.0.1", port)
        for local, remote in published_ports or []:
            ports[f"{remote}/tcp"] = local
    mounts: list[dict[str, object]] = [
        {
            "type": "bind",
            "source": workspace_path(workspace_root, project, instance),
            "target": WORKSPACE_MOUNT,
        }
    ]
    for volume in container.volumes or []:
        mounts.append(
            {
                "type": "bind",
                "source": volume.source,
                "target": volume.target,
                "read_only": volume.read_only,
            }
        )
    # Unset (None) service fields mean "engine default": collections normalize to
    # empty, and pids_limit is only forwarded when set so podman-py does not send
    # an explicit null limit.
    run_kwargs: dict[str, Any] = {}
    if container.pids_limit is not None:
        run_kwargs["pids_limit"] = container.pids_limit
    created = client.containers.run(
        image,
        name=identity,
        detach=True,
        network_mode=network_mode,
        cap_add=container.cap_add or [],
        security_opt=container.security_opt or [],
        ulimits=[
            {"Name": name, "Soft": limit.soft, "Hard": limit.hard}
            for name, limit in (container.ulimits or {}).items()
        ],
        environment=environment,
        platform=platform,
        devices=container.devices or [],
        ports=ports,
        labels=labels,
        mounts=mounts,
        **run_kwargs,
    )
    if not isinstance(created, Container):
        raise TypeError(f"expected Container, got {type(created)}")
    _wait_running(created)
    return created


def own_workspace(container: Container) -> None:
    """Set the mounted workspace ownership to the container user from inside.

    The host workspace directory is created as the plain SSH login user, so it
    starts owned by that account. Rootful Podman maps container root to host
    root and exposes host ownership directly, so a ``chown`` run as root inside
    the container also updates the bind-mounted host directory. This removes any
    need for passwordless ``sudo`` on the host.
    """
    _exec_checked(
        container,
        ["chown", f"{CONTAINER_USER}:{CONTAINER_USER}", WORKSPACE_MOUNT],
        user="0",
    )


def prepare_open_path(container: Container, open_path: str) -> None:
    """Create the editor open path inside the container for a blank project.

    Repo projects get their open directory as a side effect of ``git clone``;
    blank projects have no checkout, so the configured ``open_path`` (or the
    default ``/workspace``) would otherwise not exist. Create it as the
    container user so the editor opens a real directory.
    """
    _exec_checked(container, ["mkdir", "-p", "--", open_path], user=CONTAINER_USER)


def inject_credentials(
    container: Container,
    *,
    login_public_key: str,
    deploy_private_key: str | None,
    provider: GitProvider | None,
) -> None:
    """Write Codespace-owned SSH credentials into the development container.

    Every file is a dedicated Codespace artifact written wholesale: the
    container is a freshly created, Codespace-exclusive resource, so there is no
    pre-existing user config to preserve or merge. ``authorized_keys`` is always
    written; repo projects additionally get the deploy key ``repo_id_ed25519``
    and a fixed provider ``config``, while blank projects have no provider and
    skip both.
    """
    ssh_dir = f"/home/{CONTAINER_USER}/.ssh"
    _exec_checked(
        container,
        ["install", "-d", "-m", "0700", "-o", CONTAINER_USER, "-g", CONTAINER_USER, ssh_dir],
        user="0",
    )
    files: list[tuple[str, str, int]] = [
        ("authorized_keys", login_public_key.rstrip() + "\n", 0o600),
    ]
    if provider is not None:
        if deploy_private_key is None:
            raise ValueError("deploy_private_key is required for a repo project")
        provider_host = git_host(provider)
        provider_config = (
            f"Host {provider_host}\n"
            f"    HostName {provider_host}\n"
            "    User git\n"
            "    IdentityFile ~/.ssh/repo_id_ed25519\n"
            "    IdentitiesOnly yes\n"
            "    StrictHostKeyChecking accept-new\n"
        )
        files.append(("repo_id_ed25519", deploy_private_key, 0o600))
        files.append(("config", provider_config, 0o600))
    archive = _ssh_archive(files)
    if not container.put_archive(ssh_dir, archive):
        raise RuntimeError("failed to write container SSH credentials")
    _exec_checked(
        container,
        ["chown", "-R", f"{CONTAINER_USER}:{CONTAINER_USER}", ssh_dir],
        user="0",
    )


def clone_repo(container: Container, repo: str, provider: GitProvider) -> None:
    """Clone the configured repo, preserving an existing Git checkout unchanged."""
    target = repo_target(repo)
    present, _text = _exec(container, ["test", "-d", f"{target}/.git"], user=CONTAINER_USER)
    if present == 0:
        return
    _exec_checked(
        container,
        ["git", "clone", f"git@{git_host(provider)}:{repo}.git", target],
        user=CONTAINER_USER,
    )


def repo_git_state(container: Container, repo: str) -> RepoGitState:
    """Inspect a repo checkout for uncommitted or unpushed work before deletion.

    Returns an empty (non-blocking) state when the checkout is absent. Git
    command failures are surfaced explicitly rather than silently ignored. The
    container is started when stopped, since ``exec`` requires a running state.
    """
    _ensure_running(container)
    target = repo_target(repo)
    present, _text = _exec(container, ["test", "-d", f"{target}/.git"], user=CONTAINER_USER)
    if present != 0:
        return RepoGitState()

    detail: list[str] = []
    dirty = _git_lines(container, target, ["status", "--porcelain"])
    if dirty:
        detail.extend(dirty)
    unpushed = _git_lines(
        container,
        target,
        ["log", "--branches", "--not", "--remotes", "--oneline"],
    )
    if unpushed:
        detail.extend(unpushed)
    return RepoGitState(
        unpushed=bool(unpushed),
        uncommitted=bool(dirty),
        detail=detail[:20],
    )


def _git_lines(container: Container, target: str, args: list[str]) -> list[str]:
    exit_code, text = _exec(container, ["git", "-C", target, *args], user=CONTAINER_USER)
    if exit_code != 0:
        raise RuntimeError(f"exec git {args!r} failed ({exit_code}): {text}")
    return [line for line in text.splitlines() if line.strip()]


def purge_workspace(
    client: PodmanClient,
    container: Container,
    image: str,
    platform: ImagePlatform | None,
    workspace_root: str,
    project: str,
    instance: str,
) -> None:
    """Stop an environment and remove its workspace with the same project image."""
    container.stop(timeout=10, ignore=True)
    target = workspace_path(workspace_root, project, instance)
    helper = client.containers.run(
        image,
        name=None,
        entrypoint=["/bin/rm"],
        command=["-rf", "--", target],
        detach=True,
        platform=platform,
        user="0",
        security_opt=["disable"],
        mounts=[
            {
                "type": "bind",
                "source": workspace_root,
                "target": workspace_root,
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
    """Force-remove a managed environment container."""
    container.remove(force=True)


def container_status(container: Container) -> str | None:
    """Read status from both Podman list and inspect response shapes."""
    state = container.attrs.get("State")
    if isinstance(state, str):
        return state or None
    if isinstance(state, dict):
        status = state.get("Status")
        return str(status) if status else None
    return None


def _ensure_running(container: Container) -> None:
    """Start a stopped container so ``exec`` sessions can be created."""
    container.reload()
    if container.status == "running":
        return
    container.start()
    _wait_running(container)


def _wait_running(container: Container) -> None:
    deadline = time.monotonic() + _READY_TIMEOUT
    while time.monotonic() < deadline:
        container.reload()
        if container.status == "running":
            return
        time.sleep(_READY_INTERVAL)
    raise RuntimeError(f"container {_container_name(container)} did not reach running state")


def _exec(container: Container, command: list[str], *, user: str) -> tuple[int, str]:
    """Run one container command, failing fast when Podman returns no exit code.

    A missing (``None``) exit code means the command status is unknown; treating
    it as success would silently swallow failures, so it is rejected here. The
    returned code is a real integer callers can branch on (e.g. ``test -d``).
    """
    exit_code, output = container.exec_run(command, user=user)
    text = output.decode("utf-8", "replace") if isinstance(output, bytes) else str(output)
    if exit_code is None:
        raise RuntimeError(f"exec {command!r} returned no exit code: {text}")
    return exit_code, text


def _exec_checked(container: Container, command: list[str], *, user: str) -> None:
    exit_code, text = _exec(container, command, user=user)
    if exit_code != 0:
        raise RuntimeError(f"exec {command!r} failed ({exit_code}): {text}")


def _ssh_archive(files: list[tuple[str, str, int]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, content, mode in files:
            raw = content.encode()
            info = tarfile.TarInfo(name=name)
            info.size = len(raw)
            info.mode = mode
            archive.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()


def _container_name(container: Container) -> str:
    return str(getattr(container, "name", None) or container.id)


def _required_label(labels: dict[str, str], name: str, key: str) -> str:
    value = labels.get(key)
    if value is None or not value.strip():
        raise ValueError(f"container {name} is missing required label {key}")
    return value


def _provider(value: str, name: str) -> GitProvider:
    if value == "github":
        return "github"
    if value == "gitlab":
        return "gitlab"
    raise ValueError(f"container {name} has invalid provider label {value!r}")


def _project_type(value: str, name: str) -> ProjectType:
    if value == "repo":
        return "repo"
    if value == "blank":
        return "blank"
    raise ValueError(f"container {name} has invalid type label {value!r}")


def _platform(value: str, name: str) -> PlatformSelection:
    if value == "native":
        return "native"
    if value == "linux/amd64":
        return "linux/amd64"
    if value == "linux/arm64":
        return "linux/arm64"
    raise ValueError(f"container {name} has invalid platform label {value!r}")
