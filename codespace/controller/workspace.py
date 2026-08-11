"""Workspace ownership, repository and credential operations."""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from podman.domain.containers import Container

from codespace.controller.container import execute, execute_checked
from codespace.controller.models import (
    CONTAINER_USER,
    GitProvider,
    RepoGitState,
    git_host,
    repo_target,
)

_CLONE_TIMEOUT = 15 * 60.0
_EMPTY_REPOSITORY_MARKER = "codespace-empty-repository"


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


def prepare_open_path(container: Container, open_path: str) -> None:
    execute_checked(container, ["mkdir", "-p", "--", open_path], user=CONTAINER_USER)


def inject_deploy_key(
    container: Container,
    deploy_private_key: str,
) -> None:
    """Write the repository deploy key into a repo environment."""
    ssh_dir = f"/home/{CONTAINER_USER}/.ssh"
    if not container.put_archive(ssh_dir, _deploy_key_archive(deploy_private_key)):
        raise RuntimeError("failed to write container SSH credentials")
    execute_checked(
        container,
        [
            "chown",
            f"{CONTAINER_USER}:{CONTAINER_USER}",
            f"{ssh_dir}/repo_id_ed25519",
        ],
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
        head = execute(
            container,
            ["git", "-C", target, "rev-parse", "--verify", "HEAD"],
            user=CONTAINER_USER,
        )
        if head.code == 0:
            return
        empty = execute(
            container,
            ["test", "-f", f"{target}/.git/{_EMPTY_REPOSITORY_MARKER}"],
            user=CONTAINER_USER,
        )
        if empty.code == 0:
            return
        execute_checked(container, ["rm", "-rf", "--", target], user=CONTAINER_USER)
    else:
        target_exists = execute(
            container,
            ["test", "-e", target],
            user=CONTAINER_USER,
        )
        if target_exists.code == 0:
            raise RuntimeError(f"repository target exists but is not a checkout: {target}")

    temporary = f"{target}.codespace-clone"
    execute_checked(container, ["rm", "-rf", "--", temporary], user=CONTAINER_USER)
    execute_checked(
        container,
        [
            "git",
            "clone",
            "--depth=1",
            f"git@{git_host(provider)}:{repo}.git",
            temporary,
        ],
        user=CONTAINER_USER,
        timeout=_CLONE_TIMEOUT,
    )
    head = execute(
        container,
        ["git", "-C", temporary, "rev-parse", "--verify", "HEAD"],
        user=CONTAINER_USER,
    )
    if head.code != 0:
        execute_checked(
            container,
            ["touch", f"{temporary}/.git/{_EMPTY_REPOSITORY_MARKER}"],
            user=CONTAINER_USER,
        )
    execute_checked(container, ["mv", "--", temporary, target], user=CONTAINER_USER)


def repo_git_state(container: Container, repo: str) -> RepoGitState:
    """Return uncommitted and unpushed checkout state before deletion."""
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


def _deploy_key_archive(content: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        raw = content.encode()
        info = tarfile.TarInfo(name="repo_id_ed25519")
        info.size = len(raw)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()
