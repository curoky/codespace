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
import socket
import tarfile
import time
from contextlib import suppress
from pathlib import Path

from loguru import logger
from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import NotFound
from pydantic import BaseModel, ConfigDict

from codespace import shared

__all__ = [
    "ContainerInfo",
    "create_container",
    "ensure_workspace_dir",
    "find_container_by_workspace",
    "get_container",
    "inject_credentials",
    "list_containers",
    "pull_image",
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
    workspace: str,
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
        "starting container {} image={} repo={} workspace={} user={} ssh_port={} workspace_dir={}",
        shared.container_name(cs_id),
        image,
        repo,
        workspace,
        user,
        ssh_port,
        workspace_host_dir,
    )
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
            shared.LABEL_WORKSPACE: workspace,
            shared.LABEL_USER: user,
            shared.LABEL_IMAGE: image,
            shared.LABEL_PORT: str(ssh_port),
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


def _exec_checked(container: Container, cmd: list[str], *, user: str | None = None) -> None:
    """Run a command in the container and raise on non-zero exit."""
    exit_code, output = container.exec_run(cmd, user=user)
    if exit_code not in (0, None):
        detail = _exec_output_text(output)
        raise RuntimeError(f"exec {cmd!r} failed ({exit_code}): {detail}")


def _exec_output_text(output: object, *, stdout_only: bool = False) -> str:
    """Decode podman exec output, handling multiplexed stdout/stderr frames.

    Podman may return Docker-compatible attach frames instead of plain command
    output. Each frame has an 8-byte header: stream id, three NUL bytes, then a
    big-endian payload length. Decode only stdout when resolving values such as
    ``$HOME`` so conmon debug logs on stderr cannot corrupt the result.
    """
    if not isinstance(output, bytes):
        return str(output)
    stdout, stderr, framed = _split_exec_streams(output)
    raw = (stdout if framed else output) if stdout_only else stdout + stderr if framed else output
    return raw.decode("utf-8", "replace")


def _split_exec_streams(output: bytes) -> tuple[bytes, bytes, bool]:
    """Split Docker/Podman multiplexed exec output into stdout and stderr."""
    pos = 0
    stdout = bytearray()
    stderr = bytearray()
    while pos + 8 <= len(output):
        stream = output[pos]
        if stream not in (0, 1, 2) or output[pos + 1 : pos + 4] != b"\x00\x00\x00":
            return output, b"", False
        size = int.from_bytes(output[pos + 4 : pos + 8], "big")
        start = pos + 8
        end = start + size
        if end > len(output):
            return output, b"", False
        payload = output[start:end]
        if stream in (0, 1):
            stdout.extend(payload)
        else:
            stderr.extend(payload)
        pos = end
    if pos != len(output):
        return output, b"", False
    return bytes(stdout), bytes(stderr), True


def inject_credentials(
    client: PodmanClient,
    *,
    cs_id: str,
    user: str,
    private_key: str,
    login_pubkey: str,
    extra_keys: list[tuple[str, str]] | None = None,
) -> None:
    """Fix workspace ownership then inject deploy keys and the login pubkey.

    Steps mirror DESIGN.md §6.3:
      1. As root, ``chown`` the bind-mounted /workspace to the login user.
      2. As the login user, materialise ~/.ssh with the main repo's deploy
         private key, a git ssh config, and the client's login pubkey.

    ``extra_keys`` is a list of ``(repo, private_key)`` for extra read-only
    repos: each gets its own key file, an ssh ``Host`` alias, and a git
    ``insteadOf`` rewrite in ~/.gitconfig so ``git clone git@github.com:<repo>``
    transparently uses that key.

    Private keys are delivered via ``put_archive`` (tar over the podman API):
    never a command-line argument, never written to the agent disk.
    """
    extra_keys = extra_keys or []
    container = client.containers.get(shared.container_name(cs_id))
    logger.info(
        "injecting credentials into {} user={} extra_keys={}",
        shared.container_name(cs_id),
        user,
        len(extra_keys),
    )

    # 1) Correct ownership of the freshly bind-mounted workspace (root).
    logger.info("fixing workspace ownership for {} user={}", shared.container_name(cs_id), user)
    _exec_checked(
        container,
        ["chown", "-R", f"{user}:{user}", shared.WORKSPACE_MOUNT],
        user="0",
    )

    # Resolve the login user's home directory for archive placement.
    exit_code, out = container.exec_run(["sh", "-c", 'printf %s "$HOME"'], user=user)
    home = _exec_output_text(out, stdout_only=True).strip()
    if exit_code not in (0, None) or not home:
        raise RuntimeError(f"could not resolve home dir for user {user}")
    ssh_dir = f"{home}/.ssh"
    logger.info("resolved home for {} in {}: {}", user, shared.container_name(cs_id), home)

    # Ensure ~/.ssh exists with correct perms/ownership before writing into it.
    _exec_checked(container, ["mkdir", "-p", "-m", "700", ssh_dir], user=user)

    # Main repo: default github.com host + its read-write key.
    ssh_config_blocks = [_ssh_host_block("github.com", "github.com", "repo_id_ed25519")]
    members: list[tuple[str, str, int]] = [
        ("repo_id_ed25519", private_key, 0o600),
        ("authorized_keys", login_pubkey.rstrip("\n") + "\n", 0o600),
    ]

    # Extra repos: per-repo key file + host alias; git insteadOf rewrites below.
    for repo, key in extra_keys:
        alias = shared.extra_repo_ssh_alias(repo)
        key_file = f"repo_{alias}"
        members.append((key_file, key, 0o600))
        ssh_config_blocks.append(_ssh_host_block(alias, "github.com", key_file))

    members.append(("config", "\n".join(ssh_config_blocks), 0o600))

    archive = _multi_member_tar(members)
    logger.info(
        "writing ssh credentials into {} files={} ssh_dir={}",
        shared.container_name(cs_id),
        len(members),
        ssh_dir,
    )
    if not container.put_archive(ssh_dir, archive):
        raise RuntimeError("failed to inject credentials via put_archive")
    # put_archive preserves the tar member ownership (root); re-own to the user.
    _exec_checked(container, ["chown", "-R", f"{user}:{user}", ssh_dir], user="0")
    logger.info("ssh credentials injected into {}", shared.container_name(cs_id))

    # Extra repos also need a git insteadOf rewrite so plain github.com URLs
    # resolve to the per-repo alias (and thus the correct key).
    if extra_keys:
        logger.info(
            "writing git insteadOf rules into {} extra_repos={}",
            shared.container_name(cs_id),
            len(extra_keys),
        )
        _write_git_insteadof(
            container, home=home, user=user, extra_repos=[r for r, _ in extra_keys]
        )


def _ssh_host_block(host: str, hostname: str, key_file: str) -> str:
    """Render one ~/.ssh/config Host block pinned to a single identity."""
    return (
        f"Host {host}\n"
        f"    HostName {hostname}\n"
        "    User git\n"
        f"    IdentityFile ~/.ssh/{key_file}\n"
        "    IdentitiesOnly yes\n"
    )


def _write_git_insteadof(
    container: Container, *, home: str, user: str, extra_repos: list[str]
) -> None:
    """Append git ``insteadOf`` rewrites so extra repos use their alias/key.

    ``git@github.com:owner/name`` -> ``git@<alias>:owner/name``; git picks the
    longest-matching prefix, so the main repo (plain github.com) is unaffected.
    """
    lines = []
    for repo in extra_repos:
        alias = shared.extra_repo_ssh_alias(repo)
        lines.append(f'[url "git@{alias}:{repo}"]\n    insteadOf = git@github.com:{repo}\n')
    archive = _multi_member_tar([(".gitconfig", "".join(lines), 0o644)])
    if not container.put_archive(home, archive):
        raise RuntimeError("failed to inject git insteadOf config via put_archive")
    _exec_checked(container, ["chown", f"{user}:{user}", f"{home}/.gitconfig"], user="0")


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
    port_label = read_label(container, shared.LABEL_PORT)
    port = int(port_label) if port_label else _host_port(container) or 0
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
        status=_container_status(container),
    )


def _container_status(container: Container) -> str | None:
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


def find_container_by_workspace(
    client: PodmanClient, repo: str, workspace: str
) -> Container | None:
    """Return the managed container for a ``(repo, workspace)`` pair, if any."""
    for container in list_containers(client):
        if (
            read_label(container, shared.LABEL_REPO) == repo
            and read_label(container, shared.LABEL_WORKSPACE) == workspace
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
