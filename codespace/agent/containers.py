"""Container lifecycle, inventory and readiness probing for the agent.

All persistent metadata lives on the dev container's labels; this module reads
it back so the agent stays stateless (see DESIGN.md §6.4). The agent talks to
the host podman service over the mounted socket and never touches the host
filesystem itself.
"""

import posixpath
import socket
import time
from contextlib import suppress
from pathlib import Path
from typing import cast

from loguru import logger
from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import NotFound
from pydantic import BaseModel, ConfigDict

from codespace import shared

# Poll budget for waiting on the container to reach "running" so exec works.
_READY_TIMEOUT_S = 30.0
_READY_INTERVAL_S = 0.5
_HOST_KRB5_CONF = "/etc/krb5.conf"


class ContainerInfo(BaseModel):
    """Runtime facts resolved from a created/listed dev container."""

    model_config = ConfigDict(frozen=True)

    container_id: str
    port: int


def _host_port(container: Container, container_port: str = "22/tcp") -> int | None:
    """Resolve the host port mapped to ``container_port``, or ``None`` if unmapped."""
    container.reload()
    ports = container.ports or {}
    bindings = ports.get(container_port)
    if not bindings:
        return None
    return int(bindings[0]["HostPort"])


def _wait_running(container: Container) -> None:
    """Poll until the container is running so exec can succeed.

    Injection only needs the container running and the login user present; it
    does not depend on sshd listening (DESIGN.md §13.2).
    """
    deadline = time.monotonic() + _READY_TIMEOUT_S
    while time.monotonic() < deadline:
        container.reload()
        if container.status == "running":
            logger.info("container {} reached running state", container.name)
            return
        time.sleep(_READY_INTERVAL_S)
    raise RuntimeError(f"container {container.name} did not reach running state")


def wait_for_ssh_ready(port: int) -> None:
    """Poll localhost until the provisioned SSH port accepts TCP connections.

    Some sshd builds may accept the connection but return a pre-auth refusal
    such as ``Not allowed at this time`` instead of the normal ``SSH-`` banner.
    At this stage the agent only needs to avoid returning before the port is
    listening; key/auth correctness is handled by the client-side SSH command.
    """
    logger.info("waiting for ssh port {} to accept TCP connections", port)
    deadline = time.monotonic() + _READY_TIMEOUT_S
    last_error: str | None = None
    while time.monotonic() < deadline:
        for host in ("127.0.0.1", "::1"):
            family = socket.AF_INET6 if ":" in host else socket.AF_INET
            try:
                with socket.socket(family, socket.SOCK_STREAM) as sock:
                    sock.settimeout(_READY_INTERVAL_S)
                    sock.connect((host, port))
                logger.info("ssh port {} accepted TCP connection via {}", port, host)
                return
            except OSError as exc:
                last_error = f"{host}:{port} {exc}"
        time.sleep(_READY_INTERVAL_S)
    logger.warning("ssh port {} did not start listening: {}", port, last_error)
    raise RuntimeError(f"ssh port {port} did not start listening: {last_error}")


def _allocate_host_port() -> int:
    """Ask the kernel for a currently free host TCP port."""
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as sock:
            with suppress(OSError):
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            sock.bind(("::", 0))
            return int(sock.getsockname()[1])
    except OSError:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("", 0))
            return int(sock.getsockname()[1])


def create_container(
    client: PodmanClient,
    *,
    cs_id: str,
    image: str,
    repo: str,
    provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER,
    template: str,
    instance: str,
    user: str,
    workspace_host_dir: str,
) -> ContainerInfo:
    """Start a dev container and return its id and host SSH port.

    The bind ``source`` is a *host* path string interpreted by the host podman
    service (PoP). The directory must already exist, because podman reports a
    ``statfs ... no such file or directory`` error for absent bind sources.
    All persistent metadata is written to labels so list/delete need no
    agent-side state.
    """
    ssh_port = _allocate_host_port()
    logger.info(
        "starting container {} image={} provider={} repo={} template={} "
        "instance={} user={} ssh_port={} workspace_dir={}",
        shared.container_name(cs_id),
        image,
        provider,
        repo,
        template,
        instance,
        user,
        ssh_port,
        workspace_host_dir,
    )
    # Bind sources are interpreted by the host podman service, not by the agent
    # container. Do not probe /etc/krb5.conf from inside the agent container: it
    # may be invisible there even when the file exists on the host.
    mounts: list[dict[str, object]] = [
        {
            "type": "bind",
            "source": workspace_host_dir,
            "target": shared.WORKSPACE_MOUNT,
        },
        {
            "type": "bind",
            "source": _HOST_KRB5_CONF,
            "target": "/etc/krb5.conf",
            "read_only": True,
        },
    ]

    container = client.containers.run(
        image,
        name=shared.container_name(cs_id),
        detach=True,
        network_mode="host",
        cap_add=["NET_RAW"],
        pids_limit=-1,
        ulimits=[{"Name": "memlock", "Soft": -1, "Hard": -1}],
        environment={"SSHD_PORT": str(ssh_port)},
        labels={
            shared.LABEL_ID: cs_id,
            shared.LABEL_REPO: repo,
            shared.LABEL_PROVIDER: provider,
            shared.LABEL_TEMPLATE: template,
            shared.LABEL_INSTANCE: instance,
            shared.LABEL_USER: user,
            shared.LABEL_IMAGE: image,
            shared.LABEL_PORT: str(ssh_port),
        },
        mounts=mounts,
    )
    # detach=True always yields a Container (the streaming overloads apply only
    # when detach is False); narrow the union for the type checker.
    if not isinstance(container, Container):  # pragma: no cover - defensive
        raise TypeError(f"expected Container from run(detach=True), got {type(container)}")
    _wait_running(container)
    logger.info(
        "container {} started id={} ssh_port={}",
        shared.container_name(cs_id),
        container.id,
        ssh_port,
    )
    return ContainerInfo(container_id=container.id, port=ssh_port)


def ensure_workspace_dir(workspace_host_dir: str) -> None:
    """Create the workspace bind source directory before podman mounts it."""
    logger.info("ensuring workspace directory exists: {}", workspace_host_dir)
    Path(workspace_host_dir).mkdir(parents=True, exist_ok=True)


def pull_image(client: PodmanClient, image: str) -> None:
    """Ensure ``image`` is available locally, pulling it when needed."""
    logger.info("pulling image {}", image)
    client.images.pull(image)
    logger.info("image {} is ready", image)


def read_label(container: Container, key: str, default: str = "") -> str:
    """Read a label off a container inspect."""
    labels = container.labels or {}
    return labels.get(key, default)


def to_codespace(container: Container) -> shared.Codespace:
    """Build a wire Codespace model from a container's labels and state.

    ``deploy_keys`` is left unset (only meaningful in a create response), and
    the SSH host is omitted: the agent reports only the observable ``port``; the
    client fills in the reachable host.
    """
    port_label = read_label(container, shared.LABEL_PORT)
    port = int(port_label) if port_label else _host_port(container) or 0
    return shared.Codespace(
        id=read_label(container, shared.LABEL_ID),
        port=port,
        user=read_label(container, shared.LABEL_USER, shared.DEFAULT_CONTAINER_USER),
        container_id=container.id,
        repo=read_label(container, shared.LABEL_REPO),
        provider=cast(
            shared.GitProvider,
            read_label(container, shared.LABEL_PROVIDER, shared.DEFAULT_GIT_PROVIDER),
        ),
        template=read_label(container, shared.LABEL_TEMPLATE, shared.DEFAULT_TEMPLATE),
        instance=read_label(container, shared.LABEL_INSTANCE, shared.DEFAULT_INSTANCE),
        workspace_dir=shared.workspace_dir_name(
            read_label(container, shared.LABEL_REPO),
            read_label(container, shared.LABEL_TEMPLATE, shared.DEFAULT_TEMPLATE),
            read_label(container, shared.LABEL_INSTANCE, shared.DEFAULT_INSTANCE),
        ),
        status=container_status(container),
    )


def container_status(container: Container) -> str | None:
    """Return container status across podman-py inspect/list attr shapes."""
    attrs = getattr(container, "attrs", {}) or {}
    state = attrs.get("State") if isinstance(attrs, dict) else None
    if isinstance(state, dict):
        status = state.get("Status")
        return str(status) if status else None
    if isinstance(state, str):
        return state
    try:
        status = container.status
    except (AttributeError, KeyError, TypeError):
        return None
    return str(status) if status else None


def list_containers(client: PodmanClient) -> list[Container]:
    """List managed dev containers, scoped by the codespace name prefix."""
    managed: list[Container] = []
    for container in client.containers.list(all=True):
        name = container.name or ""
        # Only containers carrying the id label are managed codespaces; this
        # also excludes workspace dirs that share the name prefix.
        if name.startswith(shared.CONTAINER_PREFIX) and read_label(container, shared.LABEL_ID):
            managed.append(container)
    return managed


def find_container_by_instance(
    client: PodmanClient,
    repo: str,
    template: str,
    instance: str,
    *,
    provider: shared.GitProvider | None = None,
) -> Container | None:
    """Return the managed container for a ``(repo, template, instance)`` tuple, if any."""
    for container in list_containers(client):
        if (
            read_label(container, shared.LABEL_REPO) == repo
            and (
                provider is None
                or read_label(container, shared.LABEL_PROVIDER, shared.DEFAULT_GIT_PROVIDER)
                == provider
            )
            and read_label(container, shared.LABEL_TEMPLATE, shared.DEFAULT_TEMPLATE) == template
            and read_label(container, shared.LABEL_INSTANCE, shared.DEFAULT_INSTANCE) == instance
        ):
            return container
    return None


def get_container(client: PodmanClient, cs_id: str) -> Container | None:
    """Return the managed container for ``cs_id`` or ``None`` if absent."""
    try:
        container = client.containers.get(shared.container_name(cs_id))
    except NotFound:
        return None
    if not read_label(container, shared.LABEL_ID):
        return None
    return container


def remove_container(container: Container) -> None:
    """Force-remove a dev container (podman rm -f)."""
    container.remove(force=True)


def stop_container(container: Container) -> None:
    """Stop a dev container before destructive workspace cleanup."""
    container.stop(timeout=10)


def purge_workspace(client: PodmanClient, workspace_host_dir: str) -> None:
    """Delete a workspace directory using a throwaway helper container.

    Keeps the agent stateless: the removal runs inside a busybox container that
    bind-mounts the host parent directory, so the agent never touches the host FS.
    """
    normalized = posixpath.normpath(workspace_host_dir)
    workspace_parent = posixpath.dirname(normalized)
    workspace_name = posixpath.basename(normalized)
    if not workspace_name or workspace_parent in ("", normalized):
        raise ValueError(f"invalid workspace directory: {workspace_host_dir!r}")

    client.containers.run(
        "docker.io/library/busybox:latest",
        command=["sh", "-c", 'rm -rf -- "/workspaces/$1"', "purge-workspace", workspace_name],
        remove=True,
        detach=False,
        mounts=[
            {
                "type": "bind",
                "source": workspace_parent,
                "target": "/workspaces",
            }
        ],
    )
