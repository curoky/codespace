"""Workspace ownership, repository and credential operations."""

from __future__ import annotations

from podman.domain.containers import Container
from pydantic import BaseModel, ConfigDict

from controller.container import execute, execute_checked
from controller.models import CONTAINER_USER, RepoGitState

_CHECKOUT_TIMEOUT = 15 * 60.0

_DEPLOY_KEY_HELPER = "/opt/codespace/bin/codespace-deploy-key"
_CHECKOUT_HELPER = "/opt/codespace/bin/codespace-git-checkout"
_OPEN_PATH_HELPER = "/opt/codespace/bin/codespace-workspace-open-path"
_STATE_HELPER = "/opt/codespace/bin/codespace-workspace-state"


class _DeployKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    public_key: str


def generate_deploy_key(container: Container) -> str:
    """Generate or reuse the container-local deploy key and return its public key."""
    result = execute(container, [_DEPLOY_KEY_HELPER], user=CONTAINER_USER)
    if result.code != 0:
        raise RuntimeError(
            f"exec codespace-deploy-key failed ({result.code}): {result.stderr or result.stdout}"
        )
    return _DeployKey.model_validate_json(result.stdout).public_key


def bootstrap(
    container: Container,
    *,
    clone_url: str | None,
    clone_path: str,
    open_path: str,
) -> None:
    """Prepare checkout and editor paths through separate in-image helpers."""
    if clone_url is not None:
        execute_checked(
            container,
            [_CHECKOUT_HELPER, clone_url, clone_path],
            user=CONTAINER_USER,
            timeout=_CHECKOUT_TIMEOUT,
        )
    execute_checked(
        container,
        [_OPEN_PATH_HELPER, open_path],
        user=CONTAINER_USER,
    )


def checkout_git_state(container: Container, target: str) -> RepoGitState:
    """Return checkout state through the in-image state helper."""
    result = execute(container, [_STATE_HELPER, target], user=CONTAINER_USER)
    if result.code != 0:
        raise RuntimeError(
            f"exec codespace-workspace-state failed ({result.code}): "
            f"{result.stderr or result.stdout}"
        )
    return RepoGitState.model_validate_json(result.stdout)
