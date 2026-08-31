"""Workspace ownership, repository and credential operations."""

from __future__ import annotations

import io
import tarfile
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from podman.domain.containers import Container

from controller.container import execute, execute_checked
from controller.models import (
    CONTAINER_USER,
    GitProvider,
    RepoGitState,
    git_host,
)

_CLONE_TIMEOUT = 15 * 60.0

# In-image helpers that carry the multi-step checkout/state logic; the control
# plane only invokes them so the Python side stays a thin glue layer.
_BIN = "/opt/codespace/bin"


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
    execute_checked(
        container,
        [f"{_BIN}/prepare-open-path", open_path],
        user=CONTAINER_USER,
    )


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


def clone_repo(container: Container, repo: str, provider: GitProvider, target: str) -> None:
    """Clone a provider repository into ``target`` unless its checkout already exists."""
    _clone_url(container, target, f"git@{git_host(provider)}:{repo}.git")


def clone_git_url(container: Container, git_url: str, target: str) -> None:
    """Clone a raw ``git@host:owner/name.git`` URL into ``target`` unless it already exists."""
    _clone_url(container, target, git_url)


def _clone_url(container: Container, target: str, clone_url: str) -> None:
    """Clone ``clone_url`` into ``target`` via the in-image checkout helper."""
    execute_checked(
        container,
        [f"{_BIN}/git-checkout", clone_url, target],
        user=CONTAINER_USER,
        timeout=_CLONE_TIMEOUT,
    )


def repo_git_state(container: Container, target: str) -> RepoGitState:
    """Return uncommitted and unpushed checkout state before deletion."""
    return checkout_git_state(container, target)


def git_url_git_state(container: Container, target: str) -> RepoGitState:
    """Return checkout state for a raw-URL ``git`` workspace before deletion."""
    return checkout_git_state(container, target)


def checkout_git_state(container: Container, target: str) -> RepoGitState:
    """Return checkout state via the in-image ``git-state`` helper."""
    result = execute(container, [f"{_BIN}/git-state", target], user=CONTAINER_USER)
    if result.code != 0:
        raise RuntimeError(
            f"exec git-state failed ({result.code}): {result.stderr or result.stdout}"
        )
    return RepoGitState.model_validate_json(result.stdout)


def _deploy_key_archive(content: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        raw = content.encode()
        info = tarfile.TarInfo(name="repo_id_ed25519")
        info.size = len(raw)
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(raw))
    return buffer.getvalue()
