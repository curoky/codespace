"""Workspace ownership, repository and credential operations."""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from podman.domain.containers import Container

from codespace.client.container import ensure_running, execute, execute_checked
from codespace.client.models import (
    CONTAINER_USER,
    WORKSPACE_MOUNT,
    GitProvider,
    RepoGitState,
    git_host,
    repo_target,
)


@dataclass(frozen=True, slots=True)
class DeployKeypair:
    private_key: str
    public_key: str


def generate_deploy_keypair() -> DeployKeypair:
    """Generate an in-memory OpenSSH ed25519 deploy keypair."""
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


def own_workspace(container: Container) -> None:
    execute_checked(
        container,
        ["chown", f"{CONTAINER_USER}:{CONTAINER_USER}", WORKSPACE_MOUNT],
        user="0",
    )


def prepare_open_path(container: Container, open_path: str) -> None:
    execute_checked(container, ["mkdir", "-p", "--", open_path], user=CONTAINER_USER)


def inject_credentials(
    container: Container,
    *,
    deploy_private_key: str | None,
    provider: GitProvider | None,
) -> None:
    """Write the repository key and provider SSH config into a repo environment."""
    if provider is None:
        return
    if deploy_private_key is None:
        raise ValueError("deploy_private_key is required for a repo project")
    ssh_dir = f"/home/{CONTAINER_USER}/.ssh"
    execute_checked(
        container,
        ["install", "-d", "-m", "0700", "-o", CONTAINER_USER, "-g", CONTAINER_USER, ssh_dir],
        user="0",
    )
    provider_host = git_host(provider)
    provider_config = (
        f"Host {provider_host}\n"
        f"    HostName {provider_host}\n"
        "    User git\n"
        "    IdentityFile ~/.ssh/repo_id_ed25519\n"
        "    IdentitiesOnly yes\n"
        "    StrictHostKeyChecking accept-new\n"
    )
    archive = _ssh_archive(
        [
            ("repo_id_ed25519", deploy_private_key, 0o600),
            ("config", provider_config, 0o600),
        ]
    )
    if not container.put_archive(ssh_dir, archive):
        raise RuntimeError("failed to write container SSH credentials")
    execute_checked(
        container,
        ["chown", "-R", f"{CONTAINER_USER}:{CONTAINER_USER}", ssh_dir],
        user="0",
    )


def clone_repo(container: Container, repo: str, provider: GitProvider) -> None:
    """Clone a repository unless its checkout already exists."""
    target = repo_target(repo)
    present = execute(
        container,
        ["test", "-d", f"{target}/.git"],
        user=CONTAINER_USER,
    )
    if present.code == 0:
        return
    execute_checked(
        container,
        ["git", "clone", f"git@{git_host(provider)}:{repo}.git", target],
        user=CONTAINER_USER,
    )


def repo_git_state(container: Container, repo: str) -> RepoGitState:
    """Return uncommitted and unpushed checkout state before deletion."""
    ensure_running(container)
    target = repo_target(repo)
    present = execute(
        container,
        ["test", "-d", f"{target}/.git"],
        user=CONTAINER_USER,
    )
    if present.code != 0:
        return RepoGitState()

    dirty = _git_lines(container, target, ["status", "--porcelain"])
    unpushed = _git_lines(
        container,
        target,
        ["log", "--branches", "--not", "--remotes", "--oneline"],
    )
    return RepoGitState(
        unpushed=bool(unpushed),
        uncommitted=bool(dirty),
        detail=[*dirty, *unpushed][:20],
    )


def _git_lines(container: Container, target: str, args: list[str]) -> list[str]:
    result = execute(container, ["git", "-C", target, *args], user=CONTAINER_USER)
    if result.code != 0:
        raise RuntimeError(
            f"exec git {args!r} failed ({result.code}): {result.stderr or result.stdout}"
        )
    return [line for line in result.stdout.splitlines() if line.strip()]


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
