"""Container-side Workspace bootstrap, status, and Git inspection Agent.

The control plane is the sole producer of the injected
environment and validates it at its own boundary, so this trusts the
environment and keeps the logic flat. The whole implementation lives here.
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, TypeAdapter

type SourceType = Literal["github", "gitlab", "git"]
type AgentState = Literal["starting", "awaiting-provider", "ready", "failed"]

SOCKET_PATH = Path("/run/codespace-control/agent.sock")
DEPLOY_PUBLIC_KEY_PATH = Path("/home/x/.ssh/git_deploy_key_ed25519.pub")
CHECKOUT = "/usr/local/codespace/bin/checkout"

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


class RepositorySource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: SourceType
    clone_url: str
    checkout_path: str
    args: list[str]


_SOURCES = TypeAdapter(list[RepositorySource])


def run_command(
    command: list[str],
    *,
    check: bool = True,
    timeout: float = HELPER_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a helper or Git command with the Workspace user environment."""
    try:
        return subprocess.run(  # noqa: S603
            command,
            check=check,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            cwd=HELPER_HOME,
            env={**os.environ, "HOME": HELPER_HOME},
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError(f"{Path(command[0]).name} failed ({exc.returncode}): {detail}") from exc


class WorkspaceAgent:
    """Bootstrap the workspace in-process and expose its state and Git inspection."""

    def __init__(
        self,
        sources: list[RepositorySource],
        open_path: str,
        *,
        deploy_public_key_path: Path = DEPLOY_PUBLIC_KEY_PATH,
    ) -> None:
        self.sources = sources
        self.open_path = open_path
        self._deploy_public_key_path = deploy_public_key_path
        self._provider_authorized = threading.Event()
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
            needs_authorization = False
            for source in self.sources:
                if source.type in ("github", "gitlab") and not self._probe_provider(source):
                    needs_authorization = True
            if needs_authorization:
                self._set_state("awaiting-provider")
                self._provider_authorized.wait()
                self._set_state("starting")
            for source in self.sources:
                run_command(
                    [
                        CHECKOUT,
                        source.clone_url,
                        source.checkout_path,
                        *source.args,
                    ],
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
        self._provider_authorized.set()

    def status(self) -> AgentStatus:
        public_key = (
            self._deploy_public_key_path.read_text(encoding="utf-8").strip()
            if any(source.type in ("github", "gitlab") for source in self.sources)
            else None
        )
        return AgentStatus(state=self._state, public_key=public_key, error=self._error)

    def git_state(self) -> GitState:
        if not self.sources:
            raise HTTPException(409, "empty workspace has no Git state")
        if self._state != "ready":
            raise HTTPException(409, f"agent state is {self._state!r}")

        unpushed = False
        uncommitted = False
        detail: list[str] = []
        for source in self.sources:
            dirty_lines, unpushed_lines = self._repository_state(source.checkout_path)
            uncommitted = uncommitted or bool(dirty_lines)
            unpushed = unpushed or bool(unpushed_lines)
            detail.extend(
                f"{source.checkout_path}: {line}" for line in [*dirty_lines, *unpushed_lines]
            )
        return GitState(
            unpushed=unpushed,
            uncommitted=uncommitted,
            detail=detail[:20],
        )

    def _set_state(self, state: AgentState, error: str | None = None) -> None:
        self._state = state
        self._error = error

    def _probe_provider(self, source: RepositorySource) -> bool:
        command = ["git", "ls-remote", source.clone_url]
        result = run_command(command, check=False)
        if result.returncode == 0:
            return True
        detail = (result.stderr or result.stdout or "unknown error").strip()
        if "permission denied (publickey)" in detail.lower():
            return False
        raise RuntimeError(f"git failed ({result.returncode}): {detail}")

    @staticmethod
    def _repository_state(checkout_path: str) -> tuple[list[str], list[str]]:
        def git(*args: str) -> subprocess.CompletedProcess[str]:
            return run_command(["git", "-C", checkout_path, *args])

        dirty_lines = git("status", "--porcelain").stdout.splitlines()
        # Exclude agent checkpoint refs while retaining detached HEAD commits.
        revs = ["--branches", "--tags"]
        if (
            run_command(
                ["git", "-C", checkout_path, "rev-parse", "--verify", "--quiet", "HEAD"],
                check=False,
            ).returncode
            == 0
        ):
            revs.append("HEAD")
        unpushed_lines = git("log", *revs, "--not", "--remotes", "--oneline").stdout.splitlines()
        return dirty_lines, unpushed_lines


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
    agent = WorkspaceAgent(
        sources=_SOURCES.validate_json(os.environ["CODESPACE_SOURCES"]),
        open_path=os.environ["CODESPACE_OPEN_PATH"],
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
