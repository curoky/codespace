"""Credential injection and repo cloning for the codespace agent.

Key injection uses ``put_archive`` (an in-memory tar streamed over the podman
API) rather than an exec stdin stream: podman-py 5.x leaves the exec ``stdin``
parameter unimplemented, but ``put_archive`` preserves the same security
properties -- the private key is never a command-line argument, never written
to the agent's disk, and never appears in a mount table (see DESIGN.md §6.3).
"""

import io
import tarfile
from functools import cache
from importlib import resources

from loguru import logger
from podman import PodmanClient
from podman.domain.containers import Container

from codespace import shared
from codespace.agent.podman_exec import exec_checked, exec_output_text

_SSH_CONFIG_BEGIN = "# >>> codespace managed git ssh config >>>"
_SSH_CONFIG_END = "# <<< codespace managed git ssh config <<<"


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
    user: str,
    private_key: str,
    login_pubkey: str,
    provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER,
) -> None:
    """Fix workspace ownership then inject deploy keys and the login pubkey.

    Steps mirror DESIGN.md §6.3:
      1. As root, ``chown`` the bind-mounted /workspace to the login user.
      2. As the login user, materialise ~/.ssh with the main repo's deploy
         private key, a git ssh config, and the client's login pubkey.

    Private keys are delivered via ``put_archive`` (tar over the podman API):
    never a command-line argument, never written to the agent disk.
    """
    container = client.containers.get(shared.container_name(cs_id))
    logger.info(
        "injecting credentials into {} user={}",
        shared.container_name(cs_id),
        user,
    )

    # 1) Correct ownership of the freshly bind-mounted workspace (root).
    logger.info("fixing workspace ownership for {} user={}", shared.container_name(cs_id), user)
    exec_checked(
        container,
        ["chown", "-R", f"{user}:{user}", shared.WORKSPACE_MOUNT],
        user="0",
    )

    # Resolve the login user's home directory for archive placement.
    exit_code, out = container.exec_run(["sh", "-c", 'printf %s "$HOME"'], user=user)
    home = exec_output_text(out, stdout_only=True).strip()
    if exit_code not in (0, None) or not home:
        raise RuntimeError(f"could not resolve home dir for user {user}")
    ssh_dir = f"{home}/.ssh"
    logger.info("resolved home for {} in {}: {}", user, shared.container_name(cs_id), home)

    # Ensure ~/.ssh exists with correct perms/ownership before writing into it.
    exec_checked(container, ["mkdir", "-p", "-m", "700", ssh_dir], user=user)

    # Main repo: provider SSH host + its read-write key.
    git_host = shared.default_git_host(provider)
    ssh_config = _managed_ssh_config_block(_ssh_host_block(git_host, git_host, "repo_id_ed25519"))
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
    # put_archive preserves tar member ownership as root. Re-own before merging
    # the temporary config block because the merge runs as the login user.
    exec_checked(container, ["chown", "-R", f"{user}:{user}", ssh_dir], user="0")
    _append_managed_ssh_config(container, ssh_dir, user=user)
    # The merge creates/replaces ~/.ssh/config; keep the whole dir owned by user.
    exec_checked(container, ["chown", "-R", f"{user}:{user}", ssh_dir], user="0")
    logger.info("ssh credentials injected into {}", shared.container_name(cs_id))


def clone_repo(
    client: PodmanClient,
    *,
    cs_id: str,
    user: str,
    repo: str,
    provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER,
) -> None:
    """Clone the main repository into ``/workspace/<repo-name>``.

    The client calls this only after it has registered the deploy key returned
    by the agent, so a normal GitHub SSH URL can use the injected key. If the
    target already contains a Git repository, leave it untouched so a preserved
    workspace can be reused safely.
    """
    container = client.containers.get(shared.container_name(cs_id))
    git_host = shared.default_git_host(provider)
    repo_name = repo.split("/")[-1]
    target = f"{shared.WORKSPACE_MOUNT}/{repo_name}"
    logger.info("cloning repo {} from {} into {} user={}", repo, git_host, target, user)
    exec_checked(
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


def _ssh_host_block(host: str, hostname: str, key_file: str) -> str:
    """Render one ~/.ssh/config Host block pinned to a single identity."""
    return (
        f"Host {host}\n"
        f"    HostName {hostname}\n"
        "    User git\n"
        f"    IdentityFile ~/.ssh/{key_file}\n"
        "    IdentitiesOnly yes\n"
        "    StrictHostKeyChecking accept-new\n"
    )


def _managed_ssh_config_block(block: str) -> str:
    """Wrap an injected ssh config block so repeated injections can replace it."""
    return f"{_SSH_CONFIG_BEGIN}\n{block.rstrip()}\n{_SSH_CONFIG_END}\n"


def _append_managed_ssh_config(container: Container, ssh_dir: str, *, user: str) -> None:
    """Append the managed git ssh config without overwriting a user's config."""
    exec_checked(
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
        user=user,
    )


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
