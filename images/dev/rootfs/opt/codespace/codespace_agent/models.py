"""Validated workspace agent protocol models."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

MAX_REQUEST_BYTES = 4096

type WorkspaceType = Literal["repo", "git", "blank"]
type AgentState = Literal["starting", "awaiting-provider", "ready", "failed"]


class RequestError(ValueError):
    """Raised when request.json violates the fixed agent contract."""


class AgentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AgentRequest(AgentModel):
    generation: str = Field(pattern=r"^[0-9a-f]{32}$")
    workspace_type: WorkspaceType
    clone_url: str | None
    clone_path: str
    open_path: str

    @classmethod
    def load(cls, path: Path) -> AgentRequest:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise RequestError(f"cannot read {path}: {exc}") from exc
        if len(raw) > MAX_REQUEST_BYTES:
            raise RequestError("request.json exceeds 4096 bytes")
        try:
            return cls.model_validate_json(raw)
        except ValidationError as exc:
            raise RequestError(str(exc)) from exc

    @field_validator("clone_url")
    @classmethod
    def _validate_clone_url(cls, value: str | None) -> str | None:
        if value == "":
            raise ValueError("clone_url must be null or a non-empty string")
        return value

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

    @field_validator("open_path")
    @classmethod
    def _validate_open_path(cls, value: str) -> str:
        if not Path(value).is_absolute():
            raise ValueError("open_path must be an absolute path")
        return value

    @model_validator(mode="after")
    def _validate_workspace(self) -> Self:
        if self.workspace_type == "blank" and self.clone_url is not None:
            raise ValueError("blank workspace must not define clone_url")
        if self.workspace_type != "blank" and self.clone_url is None:
            raise ValueError(f"{self.workspace_type} workspace requires clone_url")
        return self


class AgentStatus(AgentModel):
    generation: str
    state: AgentState
    public_key: str | None = None
    error: str | None = None


class ProviderReadyRequest(AgentModel):
    generation: str = Field(pattern=r"^[0-9a-f]{32}$")


class GitState(AgentModel):
    unpushed: bool
    uncommitted: bool
    detail: list[str]
