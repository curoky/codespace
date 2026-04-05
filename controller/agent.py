"""Workspace agent contract and HTTP-over-UDS client."""

from __future__ import annotations

import http.client
import json
import socket
import time
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from controller.models import RepoGitState, WorkspaceType

type AgentState = Literal["starting", "awaiting-provider", "ready", "failed"]

_RESPONSE_LIMIT = 64 * 1024
_DEFAULT_TIMEOUT = 30.0
_POLL_INTERVAL = 0.2


class AgentError(RuntimeError):
    """Raised when the workspace agent rejects or returns an invalid request."""


class AgentUnavailable(AgentError):
    """Raised when the workspace agent socket cannot be reached."""


class WorkspaceAgentRequest(BaseModel):
    """Immutable bootstrap request written before the container starts."""

    model_config = ConfigDict(extra="forbid")

    generation: str = Field(pattern=r"^[0-9a-f]{32}$")
    workspace_type: WorkspaceType
    clone_url: str | None = None
    clone_path: str
    open_path: str

    @model_validator(mode="after")
    def _validate_clone_url(self) -> Self:
        if self.workspace_type == "blank" and self.clone_url is not None:
            raise ValueError("blank workspace must not define clone_url")
        if self.workspace_type != "blank" and self.clone_url is None:
            raise ValueError(f"{self.workspace_type} workspace requires clone_url")
        return self


class AgentStatus(BaseModel):
    """Current state of one agent generation."""

    model_config = ConfigDict(extra="forbid")

    generation: str = Field(pattern=r"^[0-9a-f]{32}$")
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

    def __init__(
        self,
        socket_path: Path,
        generation: str | None = None,
        *,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._socket_path = socket_path
        self._generation = generation
        self._timeout = timeout

    def status(self) -> AgentStatus:
        try:
            return AgentStatus.model_validate(self._request("GET", "/status"))
        except ValidationError as exc:
            raise AgentError("workspace agent returned an invalid status") from exc

    def provider_ready(self) -> AgentStatus:
        if self._generation is None:
            raise AgentError("provider-ready requires an expected generation")
        payload = self._request(
            "POST",
            "/provider-ready",
            {"generation": self._generation},
        )
        try:
            return AgentStatus.model_validate(payload)
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
        if self._generation is None:
            raise AgentError("waiting for bootstrap requires an expected generation")
        deadline = time.monotonic() + timeout
        last_unavailable: AgentUnavailable | None = None
        while time.monotonic() < deadline:
            try:
                status = self.status()
            except AgentUnavailable as exc:
                last_unavailable = exc
            else:
                if status.generation != self._generation:
                    raise AgentError(
                        f"workspace agent generation mismatch: expected "
                        f"{self._generation!r}, got {status.generation!r}"
                    )
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
        payload: dict[str, str] | None = None,
    ) -> object:
        body = None if payload is None else json.dumps(payload, separators=(",", ":"))
        headers = {"Content-Type": "application/json"} if body is not None else {}
        connection = _UnixHTTPConnection(self._socket_path, self._timeout)
        try:
            connection.request(method, target, body=body, headers=headers)
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
