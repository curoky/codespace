"""Workspace agent protocol state and Git inspection."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from .models import AgentConfig, AgentStatus, GitState

CONTROL_DIR = Path("/run/codespace-control")
SOCKET_PATH = CONTROL_DIR / "agent.sock"
PROVIDER_READY_PATH = CONTROL_DIR / "provider-ready"
BOOTSTRAP_READY_PATH = CONTROL_DIR / "bootstrap.ready"
BOOTSTRAP_FAILED_PATH = CONTROL_DIR / "bootstrap.failed"
DEPLOY_PUBLIC_KEY_PATH = Path("/home/x/.ssh/repo_id_ed25519.pub")

CONTAINER_UID = 5230
CONTAINER_GID = 5230
HELPER_HOME = "/home/x"
HELPER_TIMEOUT = 60.0
MAX_ERROR_LENGTH = 4096


class APIError(RuntimeError):
    """HTTP error with an explicit status code."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class CommandRunner:
    """Run Git commands as the unprivileged container user."""

    def __init__(
        self,
        *,
        run_as_user: bool = True,
        run_factory: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._run_as_user = run_as_user
        self._run_factory = run_factory

    def run(
        self,
        command: list[str],
        *,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        environment = {**os.environ, "HOME": HELPER_HOME}
        try:
            return self._run_factory(
                command,
                check=check,
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=HELPER_TIMEOUT,
                cwd=HELPER_HOME,
                env=environment,
                user=CONTAINER_UID if self._run_as_user else None,
                group=CONTAINER_GID if self._run_as_user else None,
                extra_groups=[] if self._run_as_user else None,
            )
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(
                f"{Path(command[0]).name} failed ({exc.returncode}): {detail}"
            ) from exc
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"{Path(command[0]).name} failed: {exc}") from exc


class WorkspaceAgent:
    """Expose s6 bootstrap state and Git inspection over HTTP."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        runner: CommandRunner | None = None,
        deploy_public_key_path: Path = DEPLOY_PUBLIC_KEY_PATH,
        provider_ready_path: Path = PROVIDER_READY_PATH,
        bootstrap_ready_path: Path = BOOTSTRAP_READY_PATH,
        bootstrap_failed_path: Path = BOOTSTRAP_FAILED_PATH,
    ) -> None:
        self.config = config
        self._runner = runner or CommandRunner()
        self._deploy_public_key_path = deploy_public_key_path
        self._provider_ready_path = provider_ready_path
        self._bootstrap_ready_path = bootstrap_ready_path
        self._bootstrap_failed_path = bootstrap_failed_path

    def status(self) -> AgentStatus:
        failure = self._read_failure()
        public_key = self._read_public_key() if self.config.workspace_type == "repo" else None
        if failure is not None:
            return AgentStatus(state="failed", public_key=public_key, error=failure)
        if self._path_exists(self._bootstrap_ready_path):
            return AgentStatus(state="ready", public_key=public_key)
        if self.config.workspace_type == "repo" and not self._path_exists(
            self._provider_ready_path
        ):
            return AgentStatus(state="awaiting-provider", public_key=public_key)
        return AgentStatus(state="starting", public_key=public_key)

    def git_state(self) -> GitState:
        if self.config.workspace_type == "blank":
            raise APIError(409, "blank workspace has no Git state")
        status = self.status()
        if status.state != "ready":
            raise APIError(409, f"agent state is {status.state!r}")
        target = self.config.clone_path
        try:
            repository = self._runner.run(
                ["git", "-C", target, "rev-parse", "--git-dir"],
                check=False,
            )
            if repository.returncode != 0:
                return GitState(unpushed=False, uncommitted=False, detail=[])
            dirty = self._runner.run(["git", "-C", target, "status", "--porcelain"])
            head = self._runner.run(
                ["git", "-C", target, "rev-parse", "--verify", "HEAD"],
                check=False,
            )
            unpushed_output = ""
            if head.returncode == 0:
                unpushed_output = self._runner.run(
                    [
                        "git",
                        "-C",
                        target,
                        "log",
                        "--branches",
                        "--not",
                        "--remotes",
                        "--oneline",
                    ]
                ).stdout
        except RuntimeError as exc:
            raise APIError(500, str(exc)) from exc
        dirty_lines = dirty.stdout.splitlines()
        unpushed_lines = unpushed_output.splitlines()
        return GitState(
            unpushed=bool(unpushed_lines),
            uncommitted=bool(dirty_lines),
            detail=[*dirty_lines, *unpushed_lines][:20],
        )

    def _read_public_key(self) -> str:
        try:
            public_key = self._deploy_public_key_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise APIError(500, f"cannot read deploy public key: {exc}") from exc
        if not public_key:
            raise APIError(500, "deploy public key is empty")
        return public_key

    def _read_failure(self) -> str | None:
        try:
            error = self._bootstrap_failed_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise APIError(500, f"cannot read workspace bootstrap failure: {exc}") from exc
        return error[:MAX_ERROR_LENGTH] or "workspace bootstrap failed"

    @staticmethod
    def _path_exists(path: Path) -> bool:
        try:
            path.stat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise APIError(500, f"cannot inspect workspace bootstrap state: {exc}") from exc
        return True
