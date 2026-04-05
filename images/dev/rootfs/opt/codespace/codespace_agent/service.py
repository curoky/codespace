"""Workspace bootstrap execution and agent protocol state."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from .models import AgentRequest, AgentState, AgentStatus, GitState

CONTROL_DIR = Path("/run/codespace-control")
REQUEST_PATH = CONTROL_DIR / "request.json"
SOCKET_PATH = CONTROL_DIR / "agent.sock"
PROVIDER_READY_PATH = CONTROL_DIR / "provider-ready"
STATUS_PATH = CONTROL_DIR / "status.json"
DEPLOY_PUBLIC_KEY_PATH = Path("/home/x/.ssh/repo_id_ed25519.pub")

CHECKOUT_HELPER = "/opt/codespace/bin/codespace-git-checkout"
OPEN_PATH_HELPER = "/opt/codespace/bin/codespace-workspace-open-path"

CONTAINER_UID = 5230
CONTAINER_GID = 5230
HELPER_HOME = "/home/x"
HELPER_TIMEOUT = 60.0
CHECKOUT_TIMEOUT = 15 * 60.0
MAX_ERROR_LENGTH = 4096
PROVIDER_READY_POLL_INTERVAL = 0.2


class APIError(RuntimeError):
    """HTTP error with an explicit status code."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class CommandRunner:
    """Run workspace commands as the unprivileged container user."""

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
        timeout: float = HELPER_TIMEOUT,
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
                timeout=timeout,
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


class WorkspaceBootstrap:
    """Run the automatic workspace bootstrap owned by s6."""

    def __init__(
        self,
        request: AgentRequest,
        *,
        runner: CommandRunner | None = None,
        deploy_public_key_path: Path = DEPLOY_PUBLIC_KEY_PATH,
        provider_ready_path: Path = PROVIDER_READY_PATH,
        status_path: Path = STATUS_PATH,
        provider_ready_poll_interval: float = PROVIDER_READY_POLL_INTERVAL,
    ) -> None:
        self.request = request
        self._runner = runner or CommandRunner()
        self._deploy_public_key_path = deploy_public_key_path
        self._provider_ready_path = provider_ready_path
        self._status_path = status_path
        self._provider_ready_poll_interval = provider_ready_poll_interval

    def run(self) -> AgentStatus:
        self._write_status("starting")
        public_key: str | None = None
        try:
            if self.request.workspace_type == "repo":
                public_key = self._read_public_key()
                self._write_status("awaiting-provider", public_key=public_key)
                self._wait_for_provider()
            if self.request.clone_url is not None:
                self._runner.run(
                    [CHECKOUT_HELPER, self.request.clone_url, self.request.clone_path],
                    timeout=CHECKOUT_TIMEOUT,
                )
            self._runner.run([OPEN_PATH_HELPER, self.request.open_path])
        except RuntimeError as exc:
            return self._write_status(
                "failed",
                public_key=public_key,
                error=str(exc)[:MAX_ERROR_LENGTH],
            )
        return self._write_status("ready", public_key=public_key)

    def _wait_for_provider(self) -> None:
        while not self._is_provider_ready():
            time.sleep(self._provider_ready_poll_interval)

    def _is_provider_ready(self) -> bool:
        try:
            generation = self._provider_ready_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise RuntimeError(f"cannot read provider-ready acknowledgement: {exc}") from exc
        return generation == self.request.generation

    def _read_public_key(self) -> str:
        try:
            public_key = self._deploy_public_key_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"cannot read deploy public key: {exc}") from exc
        if not public_key:
            raise RuntimeError("deploy public key is empty")
        return public_key

    def _write_status(
        self,
        state: AgentState,
        *,
        public_key: str | None = None,
        error: str | None = None,
    ) -> AgentStatus:
        status = AgentStatus(
            generation=self.request.generation,
            state=state,
            public_key=public_key,
            error=error,
        )
        try:
            _atomic_write(self._status_path, status.model_dump_json() + "\n")
        except OSError as exc:
            raise RuntimeError(f"cannot persist workspace status: {exc}") from exc
        return status


class WorkspaceAgent:
    """Expose bootstrap state and mutable control operations over HTTP."""

    def __init__(
        self,
        request: AgentRequest,
        *,
        runner: CommandRunner | None = None,
        provider_ready_path: Path = PROVIDER_READY_PATH,
        status_path: Path = STATUS_PATH,
    ) -> None:
        self.request = request
        self._runner = runner or CommandRunner()
        self._provider_ready_path = provider_ready_path
        self._status_path = status_path

    def status(self) -> AgentStatus:
        try:
            status = AgentStatus.model_validate_json(self._status_path.read_bytes())
        except FileNotFoundError:
            return self._starting_status()
        except (OSError, ValidationError) as exc:
            raise APIError(500, f"cannot read workspace status: {exc}") from exc
        if status.generation != self.request.generation:
            return self._starting_status()
        return status

    def provider_ready(self, generation: str) -> AgentStatus:
        if generation != self.request.generation:
            raise APIError(409, "generation does not match the active request")
        if self.request.workspace_type != "repo":
            raise APIError(409, "provider-ready is only valid for repo workspaces")
        status = self.status()
        if status.state not in {"awaiting-provider", "ready"}:
            raise APIError(409, f"agent state is {status.state!r}")
        try:
            _atomic_write(self._provider_ready_path, f"{self.request.generation}\n")
        except OSError as exc:
            raise APIError(500, f"cannot persist provider-ready acknowledgement: {exc}") from exc
        return status

    def git_state(self) -> GitState:
        if self.request.workspace_type == "blank":
            raise APIError(409, "blank workspace has no Git state")
        status = self.status()
        if status.state != "ready":
            raise APIError(409, f"agent state is {status.state!r}")
        target = self.request.clone_path
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

    def _starting_status(self) -> AgentStatus:
        return AgentStatus(generation=self.request.generation, state="starting")


def _atomic_write(path: Path, content: str) -> None:
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path = Path(temporary_name)
        temporary_path.chmod(0o600)
        temporary_path.replace(path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
