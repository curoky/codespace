"""Workspace bootstrap state machine and helper execution."""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from .models import AgentRequest, AgentState, AgentStatus, GitState, PublicKeyResult

CONTROL_DIR = Path("/run/codespace-control")
REQUEST_PATH = CONTROL_DIR / "request.json"
SOCKET_PATH = CONTROL_DIR / "agent.sock"
PROVIDER_READY_PATH = CONTROL_DIR / "provider-ready"

DEPLOY_KEY_HELPER = "/opt/codespace/bin/codespace-deploy-key"
CHECKOUT_HELPER = "/opt/codespace/bin/codespace-git-checkout"
OPEN_PATH_HELPER = "/opt/codespace/bin/codespace-workspace-open-path"
STATE_HELPER = "/opt/codespace/bin/codespace-workspace-state"

CONTAINER_UID = 5230
CONTAINER_GID = 5230
HELPER_HOME = "/home/x"
HELPER_TIMEOUT = 60.0
CHECKOUT_TIMEOUT = 15 * 60.0
MAX_ERROR_LENGTH = 4096


class APIError(RuntimeError):
    """HTTP error with an explicit status code."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class WorkspaceAgent:
    """Coordinate fixed bootstrap helpers and expose their state."""

    def __init__(
        self,
        request: AgentRequest,
        *,
        run_as_user: bool = True,
        run_factory: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        provider_ready_path: Path = PROVIDER_READY_PATH,
    ) -> None:
        self.request = request
        self._run_as_user = run_as_user
        self._run_factory = run_factory
        self._provider_ready_path = provider_ready_path
        self._state: AgentState = "starting"
        self._public_key: str | None = None
        self._error: str | None = None
        self._provider_ready = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._bootstrap, name="workspace-bootstrap", daemon=True)
        thread.start()
        return thread

    def status(self) -> AgentStatus:
        with self._lock:
            return AgentStatus(
                generation=self.request.generation,
                state=self._state,
                public_key=self._public_key,
                error=self._error,
            )

    def provider_ready(self, generation: str) -> AgentStatus:
        if generation != self.request.generation:
            raise APIError(409, "generation does not match the active request")
        if self.request.workspace_type != "repo":
            raise APIError(409, "provider-ready is only valid for repo workspaces")
        with self._lock:
            if self._state not in {"awaiting-provider", "ready"}:
                raise APIError(409, f"agent state is {self._state!r}")
        self._write_provider_ready()
        self._provider_ready.set()
        return self.status()

    def git_state(self) -> GitState:
        if self.request.workspace_type == "blank":
            raise APIError(409, "blank workspace has no Git state")
        with self._lock:
            if self._state != "ready":
                raise APIError(409, f"agent state is {self._state!r}")
        try:
            result = self._run_helper([STATE_HELPER, self.request.clone_path])
        except RuntimeError as exc:
            raise APIError(500, str(exc)) from exc
        try:
            return GitState.model_validate_json(result.stdout)
        except ValidationError as exc:
            raise APIError(500, "codespace-workspace-state returned an invalid result") from exc

    def _bootstrap(self) -> None:
        try:
            if self.request.workspace_type == "repo":
                public_key = self._deploy_public_key()
                with self._lock:
                    self._public_key = public_key
                    self._state = "awaiting-provider"
                if not self._is_provider_ready():
                    self._provider_ready.wait()
            if self.request.clone_url is not None:
                self._run_helper(
                    [CHECKOUT_HELPER, self.request.clone_url, self.request.clone_path],
                    timeout=CHECKOUT_TIMEOUT,
                )
            self._run_helper([OPEN_PATH_HELPER, self.request.open_path])
        except RuntimeError as exc:
            with self._lock:
                self._state = "failed"
                self._error = str(exc)[:MAX_ERROR_LENGTH]
            return
        with self._lock:
            self._state = "ready"

    def _is_provider_ready(self) -> bool:
        try:
            generation = self._provider_ready_path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise RuntimeError(f"cannot read provider-ready acknowledgement: {exc}") from exc
        return generation == self.request.generation

    def _write_provider_ready(self) -> None:
        temporary_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=self._provider_ready_path.parent,
                prefix=".provider-ready.",
                delete=False,
            ) as temporary:
                temporary_name = temporary.name
                temporary.write(f"{self.request.generation}\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            temporary_path = Path(temporary_name)
            temporary_path.chmod(0o600)
            temporary_path.replace(self._provider_ready_path)
        except OSError as exc:
            raise APIError(500, f"cannot persist provider-ready acknowledgement: {exc}") from exc
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)

    def _deploy_public_key(self) -> str:
        result = self._run_helper([DEPLOY_KEY_HELPER])
        try:
            return PublicKeyResult.model_validate_json(result.stdout).public_key
        except ValidationError as exc:
            raise RuntimeError("codespace-deploy-key returned an invalid result") from exc

    def _run_helper(
        self,
        command: list[str],
        *,
        timeout: float = HELPER_TIMEOUT,
    ) -> subprocess.CompletedProcess[str]:
        environment = {**os.environ, "HOME": HELPER_HOME}
        try:
            return self._run_factory(
                command,
                check=True,
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
