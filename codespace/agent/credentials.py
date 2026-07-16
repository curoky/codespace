"""Deploy-key generation, credential injection and repo cloning.

Key injection uses ``put_archive`` (an in-memory tar streamed over the podman
API) rather than an exec stdin stream: podman-py 5.x leaves the exec ``stdin``
parameter unimplemented, but ``put_archive`` preserves the same security
properties -- the private key is never a command-line argument, never written
to the agent's disk, and never appears in a mount table (see DESIGN.md §6.3).
"""

import io
import tarfile
from dataclasses import dataclass
from functools import cache
from importlib import resources

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from loguru import logger
from podman import PodmanClient
from podman.domain.containers import Container

from codespace import shared

_SSH_CONFIG_BEGIN = "# >>> codespace managed git ssh config >>>"
_SSH_CONFIG_END = "# <<< codespace managed git ssh config <<<"


@dataclass(frozen=True, slots=True)
class DeployKeypair:
    private_openssh: str
    public_openssh: str


def generate_deploy_keypair() -> DeployKeypair:
    """Generate an in-memory ed25519 keypair in OpenSSH format."""
    key = Ed25519PrivateKey.generate()
    private_openssh = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_openssh = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode()
    )
    return DeployKeypair(private_openssh, public_openssh)


@cache
def _load_script(name: str) -> str:
    """Read a shell script shipped under ``codespace.agent.scripts``.

    Scripts are stored as standalone ``.sh`` resources (shellcheck-able,
    unit-testable) instead of inline heredocs, and loaded via
    ``importlib.resources`` so they resolve regardless of the working directory.
    """
    return (resources.files("codespace.agent.scripts") / name).read_text(encoding="utf-8")


def inject_credentials(
    client: PodmanClient,
    *,
    cs_id: str,
    private_key: str,
    login_pubkey: str,
    provider: shared.GitProvider,
) -> None:
    """Fix workspace ownership then inject deploy keys and the login pubkey.

    Steps mirror DESIGN.md §6.3:
      1. As root, ``chown`` the bind-mounted /workspace to the login user.
      2. Materialise ~/.ssh with the main repo's deploy private key, a git ssh
         config, and the client's login pubkey.

    Private keys are delivered via ``put_archive`` (tar over the podman API):
    never a command-line argument, never written to the agent disk.
    """
    user = shared.DEFAULT_CONTAINER_USER
    container = client.containers.get(shared.container_name(cs_id))
    logger.info(
        "injecting credentials into {} user={}",
        shared.container_name(cs_id),
        user,
    )

    # 1) Correct ownership of the freshly bind-mounted workspace (root).
    logger.info("fixing workspace ownership for {} user={}", shared.container_name(cs_id), user)
    _exec_checked(
        container,
        ["chown", "-R", f"{user}:{user}", shared.WORKSPACE_MOUNT],
        user="0",
    )

    ssh_dir = f"/home/{user}/.ssh"

    # Ensure ~/.ssh exists with correct perms/ownership before writing into it.
    _exec_checked(container, ["mkdir", "-p", "-m", "700", ssh_dir], user="0")

    git_host = shared.default_git_host(provider)
    ssh_config = (
        f"{_SSH_CONFIG_BEGIN}\n"
        f"Host {git_host}\n"
        f"    HostName {git_host}\n"
        "    User git\n"
        "    IdentityFile ~/.ssh/repo_id_ed25519\n"
        "    IdentitiesOnly yes\n"
        "    StrictHostKeyChecking accept-new\n"
        f"{_SSH_CONFIG_END}\n"
    )
    members: list[tuple[str, str, int]] = [
        ("repo_id_ed25519", private_key, 0o600),
        ("authorized_keys", login_pubkey.rstrip("\n") + "\n", 0o600),
        ("config.codespace.tmp", ssh_config, 0o600),
    ]

    archive = _multi_member_tar(members)
    logger.info(
        "writing ssh credentials into {} files={} ssh_dir={}",
        shared.container_name(cs_id),
        len(members),
        ssh_dir,
    )
    if not container.put_archive(ssh_dir, archive):
        raise RuntimeError("failed to inject credentials via put_archive")
    _exec_checked(
        container,
        [
            "sh",
            "-c",
            _load_script("append_ssh_config.sh"),
            "append-ssh-config",
            ssh_dir,
            _SSH_CONFIG_BEGIN,
            _SSH_CONFIG_END,
        ],
        user="0",
    )
    # The merge creates/replaces ~/.ssh/config; keep the whole dir owned by user.
    _exec_checked(container, ["chown", "-R", f"{user}:{user}", ssh_dir], user="0")
    logger.info("ssh credentials injected into {}", shared.container_name(cs_id))


def clone_repo(
    client: PodmanClient,
    *,
    cs_id: str,
    repo: str,
    provider: shared.GitProvider,
) -> None:
    """Clone the main repository into ``/workspace/<repo-name>``.

    The client calls this only after it has registered the deploy key returned
    by the agent, so a normal GitHub SSH URL can use the injected key. If the
    target already contains a Git repository, leave it untouched so a preserved
    workspace can be reused safely.
    """
    user = shared.DEFAULT_CONTAINER_USER
    container = client.containers.get(shared.container_name(cs_id))
    git_host = shared.default_git_host(provider)
    repo_name = repo.split("/")[-1]
    target = f"{shared.WORKSPACE_MOUNT}/{repo_name}"
    logger.info("cloning repo {} from {} into {} user={}", repo, git_host, target, user)
    _exec_checked(
        container,
        [
            "sh",
            "-c",
            _load_script("clone_repo.sh"),
            "clone-repo",
            git_host,
            repo,
            target,
        ],
        user=user,
    )
    logger.info("repo {} is ready in {}", repo, target)


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


def _exec_checked(container: Container, cmd: list[str], *, user: str | None = None) -> None:
    """Run a command in the container and raise on non-zero exit."""
    exit_code, output = container.exec_run(cmd, user=user)
    if exit_code not in (0, None):
        output_text = (
            output.decode("utf-8", "replace") if isinstance(output, bytes) else str(output)
        )
        raise RuntimeError(f"exec {cmd!r} failed ({exit_code}): {output_text}")
