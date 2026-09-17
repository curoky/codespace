"""Container-side Workspace bootstrap, status, and Git inspection Agent.

The control plane is the sole producer of the injected
environment and validates it at its own boundary, so this trusts the
environment and keeps the logic flat. The whole implementation lives here.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Literal, cast

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

type SourceType = Literal["github", "gitlab", "git", "empty"]
type AgentState = Literal["starting", "awaiting-provider", "ready", "failed"]

SOCKET_PATH = Path("/run/codespace-control/agent.sock")
PROVIDER_AUTHORIZATION_PATH = Path("/var/lib/codespace/provider-authorized")
DEPLOY_PUBLIC_KEY_PATH = Path("/home/x/.ssh/repo_id_ed25519.pub")
CHECKOUT = "/opt/codespace/bin/checkout"

CONTAINER_UID = 5230
CONTAINER_GID = 5230
HELPER_HOME = "/home/x"
HELPER_TIMEOUT = 60.0
CHECKOUT_TIMEOUT = 900.0


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
    timeout: float = HELPER_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a helper or Git command as the unprivileged container user."""
    try:
        return subprocess.run(  # noqa: S603
            command,
            check=True,
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
        source_type: SourceType,
        checkout_path: str,
        open_path: str,
        clone_url: str | None = None,
        git_args: list[str] | None = None,
        *,
        deploy_public_key_path: Path = DEPLOY_PUBLIC_KEY_PATH,
        provider_authorization_path: Path = PROVIDER_AUTHORIZATION_PATH,
    ) -> None:
        self.source_type = source_type
        self.checkout_path = checkout_path
        self.open_path = open_path
        self.clone_url = clone_url
        self.git_args = git_args or []
        self._deploy_public_key_path = deploy_public_key_path
        self._provider_authorization_path = provider_authorization_path
        self._provider_authorized = threading.Event()
        if source_type in ("github", "gitlab") and provider_authorization_path.exists():
            self._provider_authorized.set()
        self._state: AgentState = "starting"
        self._error: str | None = None

    def start_bootstrap(self) -> threading.Thread:
        thread = threading.Thread(
            target=self.run_bootstrap, name="workspace-bootstrap", daemon=True
        )
        thread.start()
        return thread

    def run_bootstrap(self) -> None:
        # Runs in-process: on success state flips to ready, on any error to
        # failed with the message; /status reads that state, no on-disk marker.
        try:
            if self.source_type in ("github", "gitlab"):
                self._set_state("awaiting-provider")
                self._provider_authorized.wait()
                self._set_state("starting")
            if self.source_type != "empty":
                checkout_command = [
                    CHECKOUT,
                    cast("str", self.clone_url),
                    self.checkout_path,
                    *self.git_args,
                ]
                run_command(
                    checkout_command,
                    timeout=CHECKOUT_TIMEOUT,
                )
            run_command(["mkdir", "-p", "--", self.open_path])
        except Exception as exc:  # any failure surfaces via /status
            self._set_state("failed", str(exc).strip()[:4096] or "workspace bootstrap failed")
        else:
            self._set_state("ready")

    def authorize_provider(self) -> None:
        if self._state == "failed" or (
            self._state != "awaiting-provider" and not self._provider_authorized.is_set()
        ):
            raise HTTPException(409, f"agent state is {self._state!r}")
        # Container-local state survives Agent/container restarts, never rebuilds.
        self._provider_authorization_path.touch(mode=0o600)
        self._provider_authorized.set()

    def status(self) -> AgentStatus:
        public_key = (
            self._deploy_public_key_path.read_text(encoding="utf-8").strip()
            if self.source_type in ("github", "gitlab")
            else None
        )
        return AgentStatus(state=self._state, public_key=public_key, error=self._error)

    def git_state(self) -> GitState:
        if self.source_type == "empty":
            raise HTTPException(409, "empty workspace has no Git state")
        if self._state != "ready":
            raise HTTPException(409, f"agent state is {self._state!r}")

        def git(*args: str) -> subprocess.CompletedProcess[str]:
            return run_command(["git", "-C", self.checkout_path, *args])

        dirty_lines = git("status", "--porcelain").stdout.splitlines()
        unpushed_lines = git("log", "--all", "--not", "--remotes", "--oneline").stdout.splitlines()
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

    @app.post("/provider-ready")
    def authorize_provider() -> None:
        agent.authorize_provider()

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
    source_type = cast("SourceType", os.environ["CODESPACE_SOURCE_TYPE"])
    agent = WorkspaceAgent(
        source_type=source_type,
        checkout_path=os.environ["CODESPACE_CHECKOUT_PATH"],
        open_path=os.environ["CODESPACE_OPEN_PATH"],
        clone_url=None if source_type == "empty" else os.environ["CODESPACE_CLONE_URL"],
        git_args=cast(
            "list[str]",
            [] if source_type == "empty" else json.loads(os.environ["CODESPACE_GIT_ARGS"]),
        ),
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
