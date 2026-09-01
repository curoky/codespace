"""Container-side workspace bootstrap, status and Git inspection agent.

Personal-use agent: the controller is the sole producer of the injected
environment and validates it at its own boundary, so this trusts the
environment and keeps the logic flat. The whole implementation lives here.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal, cast

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

type WorkspaceType = Literal["repo", "git", "blank"]
type AgentState = Literal["starting", "awaiting-provider", "ready", "failed"]

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


class AgentStatus(BaseModel):
    state: AgentState
    public_key: str | None = None
    error: str | None = None


class GitState(BaseModel):
    unpushed: bool
    uncommitted: bool
    detail: list[str]


def run_command(
    command: list[str],
    *,
    check: bool = True,
    timeout: float = HELPER_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a helper or Git command as the unprivileged container user."""
    try:
        return subprocess.run(
            command,
            check=check,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            cwd=HELPER_HOME,
            env={**os.environ, "HOME": HELPER_HOME},
            user=CONTAINER_UID,
            group=CONTAINER_GID,
            extra_groups=[],
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"{Path(command[0]).name} failed ({exc.returncode}): {detail}") from exc


class WorkspaceAgent:
    """Bootstrap the workspace in-process and expose its state and Git inspection."""

    def __init__(
        self,
        workspace_type: WorkspaceType,
        clone_path: str,
        open_path: str,
        clone_url: str | None = None,
        *,
        deploy_public_key_path: Path = DEPLOY_PUBLIC_KEY_PATH,
        provider_ready_path: Path = PROVIDER_READY_PATH,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.workspace_type = workspace_type
        self.clone_path = clone_path
        self.open_path = open_path
        self.clone_url = clone_url
        self._deploy_public_key_path = deploy_public_key_path
        self._provider_ready_path = provider_ready_path
        self._sleep = sleep
        self._state: AgentState = "starting"
        self._error: str | None = None

    def start_bootstrap(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_bootstrap, name="workspace-bootstrap", daemon=True)
        thread.start()
        return thread

    def run_bootstrap(self) -> None:
        # Runs in-process: on success state flips to ready, on any error to
        # failed with the message; /status reads that state, no on-disk marker.
        try:
            if self.workspace_type == "repo":
                self._set_state("awaiting-provider")
                while not self._provider_ready_path.exists():
                    self._sleep(PROVIDER_POLL_INTERVAL)
                self._set_state("starting")
            if self.workspace_type in ("repo", "git"):
                if self.clone_url is None:
                    raise RuntimeError("clone_url is required for checkout")
                run_command(
                    [GIT_CHECKOUT, self.clone_url, self.clone_path],
                    timeout=CHECKOUT_TIMEOUT,
                )
            run_command(["mkdir", "-p", "--", self.open_path])
        except Exception as exc:  # any failure surfaces via /status
            self._set_state("failed", str(exc).strip()[:4096] or "workspace bootstrap failed")
        else:
            self._set_state("ready")

    def status(self) -> AgentStatus:
        public_key = (
            self._deploy_public_key_path.read_text(encoding="utf-8").strip()
            if self.workspace_type == "repo"
            else None
        )
        return AgentStatus(state=self._state, public_key=public_key, error=self._error)

    def git_state(self) -> GitState:
        if self.workspace_type == "blank":
            raise HTTPException(409, "blank workspace has no Git state")
        if self._state != "ready":
            raise HTTPException(409, f"agent state is {self._state!r}")

        def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
            return run_command(["git", "-C", self.clone_path, *args], check=check)

        if git("rev-parse", "--git-dir", check=False).returncode != 0:
            return GitState(unpushed=False, uncommitted=False, detail=[])
        dirty_lines = git("status", "--porcelain").stdout.splitlines()
        unpushed_lines: list[str] = []
        if git("rev-parse", "--verify", "HEAD", check=False).returncode == 0:
            unpushed_lines = git(
                "log", "--branches", "--not", "--remotes", "--oneline"
            ).stdout.splitlines()
        return GitState(
            unpushed=bool(unpushed_lines),
            uncommitted=bool(dirty_lines),
            detail=[*dirty_lines, *unpushed_lines][:20],
        )

    def _set_state(self, state: AgentState, error: str | None = None) -> None:
        self._state = state
        self._error = error


def create_app(agent: WorkspaceAgent) -> FastAPI:
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    app.router.redirect_slashes = False

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
    if not os.environ.get("CODESPACE_WORKSPACE_TYPE"):
        print("CODESPACE_WORKSPACE_TYPE unset; workspace agent idle", flush=True)
        signal.pause()
        return
    CONTROL_DIR.mkdir(parents=True, exist_ok=True)
    agent = WorkspaceAgent(
        workspace_type=cast("WorkspaceType", os.environ["CODESPACE_WORKSPACE_TYPE"]),
        clone_path=os.environ["CODESPACE_CLONE_PATH"],
        open_path=os.environ["CODESPACE_OPEN_PATH"],
        clone_url=os.environ.get("CODESPACE_CLONE_URL") or None,
    )
    agent.start_bootstrap()
    server, server_socket = build_server(agent)
    try:
        server.run(sockets=[server_socket])
    finally:
        server_socket.close()
        SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
