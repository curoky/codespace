"""Workspace agent contract and HTTP-over-UDS client."""

from __future__ import annotations

import http.client
import json
import socket
import time
from pathlib import Path
from typing import Annotated, Literal, overload

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from codespace.runtime.container import NonBlankString
from codespace.workspaces.models import RepoGitState

_RESPONSE_LIMIT = 64 * 1024
_DEFAULT_TIMEOUT = 30.0
_POLL_INTERVAL = 0.2


class AgentError(RuntimeError):
    """Raised when the workspace agent rejects or returns an invalid request."""


class AgentUnavailable(AgentError):
    """Raised when the workspace agent socket cannot be reached."""


class _StatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    public_key: NonBlankString | None
    error: NonBlankString | None


class BootstrapStatus(_StatusResponse):
    state: Literal["starting", "ready"]
    error: None


class ProviderStatus(_StatusResponse):
    state: Literal["awaiting-provider"]
    public_key: NonBlankString
    error: None


class FailedStatus(_StatusResponse):
    state: Literal["failed"]
    error: NonBlankString


type AgentStatus = Annotated[
    BootstrapStatus | ProviderStatus | FailedStatus, Field(discriminator="state")
]
_STATUS: TypeAdapter[AgentStatus] = TypeAdapter(AgentStatus)


class _ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    detail: NonBlankString


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
            return _STATUS.validate_python(self._request("GET", "/status"))
        except ValidationError as exc:
            raise AgentError("workspace agent returned an invalid status") from exc

    def git_state(self) -> RepoGitState:
        try:
            return RepoGitState.model_validate(self._request("GET", "/git-state"))
        except ValidationError as exc:
            raise AgentError("workspace agent returned an invalid Git state") from exc

    @overload
    def wait_for(
        self, state: Literal["awaiting-provider"], *, timeout: float
    ) -> ProviderStatus: ...

    @overload
    def wait_for(self, state: Literal["ready"], *, timeout: float) -> BootstrapStatus: ...

    def wait_for(
        self,
        state: Literal["awaiting-provider", "ready"],
        *,
        timeout: float,
    ) -> BootstrapStatus | ProviderStatus:
        """Wait for the desired state, retrying only socket availability."""
        deadline = time.monotonic() + timeout
        last_unavailable: AgentUnavailable | None = None
        while time.monotonic() < deadline:
            try:
                status = self.status()
            except AgentUnavailable as exc:
                last_unavailable = exc
            else:
                if status.state == "failed":
                    raise AgentError(status.error)
                if status.state == state:
                    return status
            time.sleep(_POLL_INTERVAL)
        detail = f": {last_unavailable}" if last_unavailable is not None else ""
        raise AgentUnavailable(
            f"workspace agent did not reach {state!r} within {timeout:g}s{detail}"
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
            try:
                error = _ErrorResponse.model_validate(decoded)
            except ValidationError as exc:
                raise AgentError(
                    f"workspace agent returned an invalid error response ({response.status})"
                ) from exc
            raise AgentError(
                f"workspace agent {method} {target} failed ({response.status}): {error.detail}"
            )
        return decoded
