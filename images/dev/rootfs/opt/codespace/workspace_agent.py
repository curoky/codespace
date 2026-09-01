"""Container-side workspace status and Git inspection agent."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

type WorkspaceType = Literal["repo", "git", "blank"]
type AgentState = Literal["starting", "awaiting-provider", "ready", "failed"]

WORKSPACE_TYPE_ENV = "CODESPACE_WORKSPACE_TYPE"
WORKSPACE_CLONE_PATH_ENV = "CODESPACE_CLONE_PATH"

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


class ConfigError(ValueError):
    """Raised when the container environment violates the agent contract."""


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AgentConfig(AgentModel):
    workspace_type: WorkspaceType
    clone_path: str

    @classmethod
    def load(cls, environment: Mapping[str, str]) -> AgentConfig:
        try:
            values = {
                "workspace_type": environment[WORKSPACE_TYPE_ENV],
                "clone_path": environment[WORKSPACE_CLONE_PATH_ENV],
            }
        except KeyError as exc:
            raise ConfigError(f"missing container environment variable: {exc.args[0]}") from exc
        try:
            return cls.model_validate(values)
        except ValidationError as exc:
            raise ConfigError(str(exc)) from exc

    @field_validator("clone_path")
    @classmethod
    def _validate_clone_path(cls, value: str) -> str:
        path = Path(value)
        if (
            not path.is_absolute()
            or ".." in path.parts
            or str(path) != value
            or (value != "/workspace" and not value.startswith("/workspace/"))
        ):
            raise ValueError("clone_path must be a normalized path below /workspace")
        return value


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
    """Expose managed workspace initialization state and Git inspection."""

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
        # home-init 是 oneshot: agent 能运行即代表 home 初始化已成功, 故就绪判定
        # 只看 bootstrap, 不再读 home marker.
        public_key = self._read_public_key() if self.config.workspace_type == "repo" else None
        if failure := self._read_failure(self._bootstrap_failed_path):
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

    @staticmethod
    def _read_failure(path: Path) -> str | None:
        try:
            error = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise APIError(500, f"cannot read workspace initialization failure: {exc}") from exc
        return error[:MAX_ERROR_LENGTH] or "workspace initialization failed"

    @staticmethod
    def _path_exists(path: Path) -> bool:
        try:
            path.stat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise APIError(500, f"cannot inspect workspace initialization state: {exc}") from exc
        return True


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
    # runs have no controller, so idle instead of serving the agent socket.
    if not os.environ.get(WORKSPACE_TYPE_ENV):
        print(f"{WORKSPACE_TYPE_ENV} unset; workspace agent idle", flush=True)
        signal.pause()
        return
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    agent = WorkspaceAgent(AgentConfig.load(os.environ))
    server, server_socket = build_server(agent)
    try:
        server.run(sockets=[server_socket])
    finally:
        server_socket.close()
        SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
