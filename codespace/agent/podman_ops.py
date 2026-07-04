"""Podman orchestration for the codespace agent (Podman-out-of-Podman).

All persistent metadata lives on the dev container's labels; this module reads
it back so the agent stays stateless (see DESIGN.md §6.4). The agent talks to
the host podman service over the mounted socket and never touches the host
filesystem itself.

Key injection uses ``put_archive`` (an in-memory tar streamed over the podman
API) rather than an exec stdin stream: podman-py 5.x leaves the exec ``stdin``
parameter unimplemented, but ``put_archive`` preserves the same security
properties -- the private key is never a command-line argument, never written
to the agent's disk, and never appears in a mount table (see DESIGN.md §6.3).
"""

import io
import tarfile
import time

from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import NotFound, PodmanError
from pydantic import BaseModel, ConfigDict

from codespace import shared

__all__ = [
    "Container",
    "ContainerInfo",
    "PodmanError",
    "create_container",
    "get_container",
    "inject_credentials",
    "list_containers",
    "purge_workspace",
    "read_label",
    "remove_container",
    "to_codespace",
]

# Poll budget for waiting on the container to reach "running" so exec works.
_READY_TIMEOUT_S = 30.0
_READY_INTERVAL_S = 0.5


class ContainerInfo(BaseModel):
    """Runtime facts resolved from a created/listed dev container."""

    model_config = ConfigDict(frozen=True)

    container_id: str
    port: int


def _host_port(container: Container, container_port: str = "22/tcp") -> int:
    """Resolve the host port mapped to ``container_port`` from an inspect."""
    container.reload()
    ports = container.ports or {}
    bindings = ports.get(container_port)
    if not bindings:
        raise RuntimeError(f"container has no host mapping for {container_port}")
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
            return
        time.sleep(_READY_INTERVAL_S)
    raise RuntimeError(f"container {container.name} did not reach running state")


def create_container(
    client: PodmanClient,
    *,
    cs_id: str,
    image: str,
    repo: str,
    workspace: str,
    user: str,
    workspace_host_dir: str,
) -> ContainerInfo:
    """Start a dev container and return its id and host SSH port.

    The bind ``source`` is a *host* path string interpreted by the host podman
    service (PoP); podman creates it (root-owned) if absent. All persistent
    metadata is written to labels so list/delete need no agent-side state.
    """
    container = client.containers.run(
        image,
        name=shared.container_name(cs_id),
        detach=True,
        ports={"22/tcp": None},
        labels={
            shared.LABEL_ID: cs_id,
            shared.LABEL_REPO: repo,
            shared.LABEL_WORKSPACE: workspace,
            shared.LABEL_USER: user,
            shared.LABEL_IMAGE: image,
        },
        mounts=[
            {
                "type": "bind",
                "source": workspace_host_dir,
                "target": shared.WORKSPACE_MOUNT,
            }
        ],
    )
    # detach=True always yields a Container (the streaming overloads apply only
    # when detach is False); narrow the union for the type checker.
    if not isinstance(container, Container):  # pragma: no cover - defensive
        raise TypeError(f"expected Container from run(detach=True), got {type(container)}")
    _wait_running(container)
    return ContainerInfo(container_id=container.id, port=_host_port(container))


def _exec_checked(container: Container, cmd: list[str], *, user: str | None = None) -> None:
    """Run a command in the container and raise on non-zero exit."""
    exit_code, output = container.exec_run(cmd, user=user)
    if exit_code not in (0, None):
        detail = output.decode("utf-8", "replace") if isinstance(output, bytes) else output
        raise RuntimeError(f"exec {cmd!r} failed ({exit_code}): {detail}")


def inject_credentials(
    client: PodmanClient,
    *,
    cs_id: str,
    user: str,
    private_key: str,
    login_pubkey: str,
) -> None:
    """Fix workspace ownership then inject the deploy key and login pubkey.

    Steps mirror DESIGN.md §6.3:
      1. As root, ``chown`` the bind-mounted /workspace to the login user.
      2. As the login user, materialise ~/.ssh with the deploy private key,
         a git ssh config pinned to that key, and the client's login pubkey.

    The private key is delivered via ``put_archive`` (tar over the podman API):
    it is never a command-line argument and never written to the agent disk.
    """
    container = client.containers.get(shared.container_name(cs_id))

    # 1) Correct ownership of the freshly bind-mounted workspace (root).
    _exec_checked(
        container,
        ["chown", "-R", f"{user}:{user}", shared.WORKSPACE_MOUNT],
        user="0",
    )

    # Resolve the login user's home directory for archive placement.
    exit_code, out = container.exec_run(["sh", "-c", 'printf %s "$HOME"'], user=user)
    home = out.decode("utf-8").strip() if isinstance(out, bytes) else str(out).strip()
    if exit_code not in (0, None) or not home:
        raise RuntimeError(f"could not resolve home dir for user {user}")
    ssh_dir = f"{home}/.ssh"

    # Ensure ~/.ssh exists with correct perms/ownership before writing into it.
    _exec_checked(
        container,
        ["mkdir", "-p", "-m", "700", ssh_dir],
        user=user,
    )

    git_ssh_config = (
        "Host github.com\n"
        "    HostName github.com\n"
        "    User git\n"
        "    IdentityFile ~/.ssh/repo_id_ed25519\n"
        "    IdentitiesOnly yes\n"
    )
    # authorized_keys and git config are not secret; the private key is.
    archive = _multi_member_tar(
        [
            ("repo_id_ed25519", private_key, 0o600),
            ("config", git_ssh_config, 0o600),
            ("authorized_keys", login_pubkey.rstrip("\n") + "\n", 0o600),
        ]
    )
    if not container.put_archive(ssh_dir, archive):
        raise RuntimeError("failed to inject credentials via put_archive")

    # put_archive preserves the tar member ownership (root); re-own to the user.
    _exec_checked(container, ["chown", "-R", f"{user}:{user}", ssh_dir], user="0")


def _multi_member_tar(members: list[tuple[str, str, int]]) -> bytes:
    """Build a tar archive containing several files for ``put_archive``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, content, mode in members:
            raw = content.encode("utf-8")
            info = tarfile.TarInfo(name=name)
            info.size = len(raw)
            info.mode = mode
            tar.addfile(info, io.BytesIO(raw))
    return buf.getvalue()


def read_label(container: Container, key: str, default: str = "") -> str:
    """Read a label off a container inspect."""
    labels = container.labels or {}
    return labels.get(key, default)


def to_codespace(container: Container) -> shared.Codespace:
    """Build a wire Codespace model from a container's labels and state.

    ``deploy_public_key`` is left unset (only meaningful in a create response),
    and the SSH host is omitted: the agent reports only the observable ``port``;
    the client fills in the reachable host.
    """
    try:
        port = _host_port(container)
    except RuntimeError:
        port = 0
    return shared.Codespace(
        id=read_label(container, shared.LABEL_ID),
        port=port,
        user=read_label(container, shared.LABEL_USER, shared.DEFAULT_CONTAINER_USER),
        container_id=container.id,
        repo=read_label(container, shared.LABEL_REPO),
        workspace=read_label(container, shared.LABEL_WORKSPACE),
        workspace_dir=shared.workspace_dir_name(
            read_label(container, shared.LABEL_REPO),
            read_label(container, shared.LABEL_WORKSPACE),
        ),
        status=container.status,
    )


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


def purge_workspace(client: PodmanClient, workspace_host_dir: str) -> None:
    """Delete a workspace directory using a throwaway helper container.

    Keeps the agent stateless: the removal runs inside a busybox container that
    bind-mounts the host directory, so the agent never touches the host FS.
    """
    client.containers.run(
        "docker.io/library/busybox:latest",
        command=["sh", "-c", "rm -rf /t/* /t/.[!.]* /t/..?* 2>/dev/null; true"],
        remove=True,
        detach=False,
        mounts=[
            {
                "type": "bind",
                "source": workspace_host_dir,
                "target": "/t",
            }
        ],
    )
