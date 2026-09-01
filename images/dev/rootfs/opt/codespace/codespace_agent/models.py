"""Validated workspace agent protocol models."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

type WorkspaceType = Literal["repo", "git", "blank"]
type AgentState = Literal["starting", "awaiting-provider", "ready", "failed"]

WORKSPACE_TYPE_ENV = "CODESPACE_WORKSPACE_TYPE"
WORKSPACE_CLONE_PATH_ENV = "CODESPACE_CLONE_PATH"


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
