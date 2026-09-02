"""Workspace agent contract and HTTP-over-UDS client."""

from __future__ import annotations

import http.client
import json
import socket
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from codespace.workspaces.models import RepoGitState

type AgentState = Literal["starting", "awaiting-provider", "ready", "failed"]

_RESPONSE_LIMIT = 64 * 1024
_DEFAULT_TIMEOUT = 30.0
_POLL_INTERVAL = 0.2


class AgentError(RuntimeError):
    """Raised when the workspace agent rejects or returns an invalid request."""


class AgentUnavailable(AgentError):
    """Raised when the workspace agent socket cannot be reached."""


class AgentStatus(BaseModel):
    """Current state of the container workspace bootstrap."""

    model_config = ConfigDict(extra="forbid")

    state: AgentState
    public_key: str | None = None
    error: str | None = None


class _UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: Path, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(self.timeout)
        connection.connect(str(self._socket_path))
        self.sock = connection


class WorkspaceAgentClient:
    """Call the fixed workspace agent API through a local Unix socket."""

    def __init__(self, socket_path: Path) -> None:
        self._socket_path = socket_path

    def status(self) -> AgentStatus:
        try:
            return AgentStatus.model_validate(self._request("GET", "/status"))
        except ValidationError as exc:
            raise AgentError("workspace agent returned an invalid status") from exc

    def git_state(self) -> RepoGitState:
        try:
            return RepoGitState.model_validate(self._request("GET", "/git-state"))
        except ValidationError as exc:
            raise AgentError("workspace agent returned an invalid Git state") from exc

    def wait_for(
        self,
        states: set[AgentState],
        *,
        timeout: float,
    ) -> AgentStatus:
        """Wait for one desired state, retrying only socket availability."""
        deadline = time.monotonic() + timeout
        last_unavailable: AgentUnavailable | None = None
        while time.monotonic() < deadline:
            try:
                status = self.status()
            except AgentUnavailable as exc:
                last_unavailable = exc
            else:
                if status.state == "failed":
                    raise AgentError(status.error or "workspace agent bootstrap failed")
                if status.state in states:
                    return status
            time.sleep(_POLL_INTERVAL)
        detail = f": {last_unavailable}" if last_unavailable is not None else ""
        expected = ", ".join(sorted(states))
        raise AgentUnavailable(
            f"workspace agent did not reach [{expected}] within {timeout:g}s{detail}"
        )

    def _request(
        self,
        method: str,
        target: str,
    ) -> object:
        connection = _UnixHTTPConnection(self._socket_path, _DEFAULT_TIMEOUT)
        try:
            connection.request(method, target)
            response = connection.getresponse()
            raw = response.read(_RESPONSE_LIMIT + 1)
        except (OSError, http.client.HTTPException) as exc:
            raise AgentUnavailable(
                f"workspace agent at {self._socket_path} is unavailable: {exc}"
            ) from exc
        finally:
            connection.close()
        if len(raw) > _RESPONSE_LIMIT:
            raise AgentError("workspace agent response exceeds 64 KiB")
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AgentError("workspace agent returned invalid JSON") from exc
        if not 200 <= response.status < 300:
            detail = decoded.get("error") if isinstance(decoded, dict) else None
            raise AgentError(
                f"workspace agent {method} {target} failed ({response.status}): "
                f"{detail or response.reason}"
            )
        return decoded
