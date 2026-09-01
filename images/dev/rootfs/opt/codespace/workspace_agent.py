"""Container-side workspace bootstrap, status and Git inspection agent."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

type WorkspaceType = Literal["repo", "git", "blank"]
type AgentState = Literal["starting", "awaiting-provider", "ready", "failed"]

WORKSPACE_TYPE_ENV = "CODESPACE_WORKSPACE_TYPE"
WORKSPACE_CLONE_URL_ENV = "CODESPACE_CLONE_URL"
WORKSPACE_CLONE_PATH_ENV = "CODESPACE_CLONE_PATH"
WORKSPACE_OPEN_PATH_ENV = "CODESPACE_OPEN_PATH"

CONTROL_DIR = Path("/run/codespace-control")
SOCKET_PATH = CONTROL_DIR / "agent.sock"
PROVIDER_READY_PATH = CONTROL_DIR / "provider-ready"
DEPLOY_PUBLIC_KEY_PATH = Path("/home/x/.ssh/repo_id_ed25519.pub")
GIT_CHECKOUT = "/opt/codespace/bin/git-checkout"

CONTAINER_UID = 5230
CONTAINER_GID = 5230
HELPER_HOME = "/home/x"
HELPER_TIMEOUT = 60.0
CHECKOUT_TIMEOUT = 900.0
PROVIDER_POLL_INTERVAL = 0.2
MAX_ERROR_LENGTH = 4096


class ConfigError(ValueError):
    """Raised when the container environment violates the agent contract."""


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _normalized_workspace_path(value: str) -> str:
    path = Path(value)
    if (
        not path.is_absolute()
        or ".." in path.parts
        or str(path) != value
        or (value != "/workspace" and not value.startswith("/workspace/"))
    ):
        raise ValueError("must be a normalized path below /workspace")
    return value


class AgentConfig(AgentModel):
    workspace_type: WorkspaceType
    clone_path: str
    open_path: str
    clone_url: str | None = None

    @classmethod
    def load(cls, environment: Mapping[str, str]) -> AgentConfig:
        try:
            values: dict[str, str] = {
                "workspace_type": environment[WORKSPACE_TYPE_ENV],
                "clone_path": environment[WORKSPACE_CLONE_PATH_ENV],
                "open_path": environment[WORKSPACE_OPEN_PATH_ENV],
            }
        except KeyError as exc:
            raise ConfigError(f"missing container environment variable: {exc.args[0]}") from exc
        if clone_url := environment.get(WORKSPACE_CLONE_URL_ENV):
            values["clone_url"] = clone_url
        try:
            return cls.model_validate(values)
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc

    @field_validator("clone_path", "open_path")
    @classmethod
    def _validate_paths(cls, value: str) -> str:
        return _normalized_workspace_path(value)

    @model_validator(mode="after")
    def _require_clone_url(self) -> AgentConfig:
        if self.workspace_type in ("repo", "git") and not self.clone_url:
            raise ValueError("clone_url is required for repo and git workspaces")
        return self


class AgentStatus(AgentModel):
    state: AgentState
    public_key: str | None = None
    error: str | None = None


class GitState(AgentModel):
    unpushed: bool
    uncommitted: bool
    detail: list[str]


class APIError(RuntimeError):
    """HTTP error with an explicit status code."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class CommandRunner:
    """Run helper and Git commands as the unprivileged container user."""

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
        timeout: float = HELPER_TIMEOUT,
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


class WorkspaceAgent:
    """Bootstrap the workspace in-process and expose its state and Git inspection."""

    def __init__(
        self,
        config: AgentConfig,
        *,
        runner: CommandRunner | None = None,
        deploy_public_key_path: Path = DEPLOY_PUBLIC_KEY_PATH,
        provider_ready_path: Path = PROVIDER_READY_PATH,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._runner = runner or CommandRunner()
        self._deploy_public_key_path = deploy_public_key_path
        self._provider_ready_path = provider_ready_path
        self._sleep = sleep
        self._state_lock = threading.Lock()
        self._state: AgentState = "starting"
        self._error: str | None = None

    def start_bootstrap(self) -> threading.Thread:
        thread = threading.Thread(
            target=self.run_bootstrap,
            name="workspace-bootstrap",
            daemon=True,
        )
        thread.start()
        return thread

    def run_bootstrap(self) -> None:
        # Bootstrap runs in-process: on success the in-memory state flips to
        # ready, on any error to failed with a truncated message. The status
        # endpoint reads that state, so no on-disk bootstrap marker is needed.
        try:
            self._bootstrap()
        except Exception as exc:  # any failure surfaces via /status
            self._set_state("failed", _truncate(str(exc)))
        else:
            self._set_state("ready")

    def _bootstrap(self) -> None:
        if self.config.workspace_type == "repo":
            self._set_state("awaiting-provider")
            self._wait_for_provider()
            self._set_state("starting")
        if self.config.workspace_type in ("repo", "git"):
            self._checkout()
        self._runner.run(["mkdir", "-p", "--", self.config.open_path])

    def _wait_for_provider(self) -> None:
        while not self._path_exists(self._provider_ready_path):
            self._sleep(PROVIDER_POLL_INTERVAL)

    def _checkout(self) -> None:
        if self.config.clone_url is None:
            raise RuntimeError("clone_url is required for checkout")
        self._runner.run(
            [GIT_CHECKOUT, self.config.clone_url, self.config.clone_path],
            timeout=CHECKOUT_TIMEOUT,
        )

    def status(self) -> AgentStatus:
        with self._state_lock:
            state, error = self._state, self._error
        public_key = self._read_public_key() if self.config.workspace_type == "repo" else None
        return AgentStatus(state=state, public_key=public_key, error=error)

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

    def _set_state(self, state: AgentState, error: str | None = None) -> None:
        with self._state_lock:
            self._state = state
            self._error = error

    def _read_public_key(self) -> str:
        try:
            public_key = self._deploy_public_key_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise APIError(500, f"cannot read deploy public key: {exc}") from exc
        if not public_key:
            raise APIError(500, "deploy public key is empty")
        return public_key

    @staticmethod
    def _path_exists(path: Path) -> bool:
        try:
            path.stat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise APIError(500, f"cannot inspect workspace bootstrap state: {exc}") from exc
        return True


def _truncate(message: str) -> str:
    message = message.strip()
    return message[:MAX_ERROR_LENGTH] or "workspace bootstrap failed"


def create_app(agent: WorkspaceAgent) -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.router.redirect_slashes = False

    @app.exception_handler(APIError)
    async def handle_api_error(
        request: Request,
        exc: APIError,
    ) -> JSONResponse:
        del request
        return JSONResponse(status_code=exc.status_code, content={"error": str(exc)})

    @app.get("/status")
    def status() -> AgentStatus:
        return agent.status()

    @app.get("/git-state")
    def git_state() -> GitState:
        return agent.git_state()

    return app


def build_server(
    agent: WorkspaceAgent,
    socket_path: Path = SOCKET_PATH,
) -> tuple[uvicorn.Server, socket.socket]:
    socket_path.unlink(missing_ok=True)
    config = uvicorn.Config(
        create_app(agent),
        uds=str(socket_path),
        access_log=False,
        log_config=None,
        server_header=False,
        date_header=False,
    )
    return uvicorn.Server(config), config.bind_socket()


def main() -> None:
    # Controller-managed environments set CODESPACE_WORKSPACE_TYPE. Generic image
    # runs have no controller, so idle instead of bootstrapping and serving.
    if not os.environ.get(WORKSPACE_TYPE_ENV):
        print(f"{WORKSPACE_TYPE_ENV} unset; workspace agent idle", flush=True)
        signal.pause()
        return
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    agent = WorkspaceAgent(AgentConfig.load(os.environ))
    agent.start_bootstrap()
    server, server_socket = build_server(agent)
    try:
        server.run(sockets=[server_socket])
    finally:
        server_socket.close()
        SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
