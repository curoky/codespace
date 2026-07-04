"""YAML configuration for the local Codespace Web GUI."""

import os
import re
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from codespace import shared

CONFIG_ENV = "CODESPACE_CONFIG"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "codespace" / "config.yaml"
AGENT_ID_RE = re.compile(r"^[\w.-]+$")


class AgentProfile(BaseModel):
    """One configured agent profile."""

    id: str = ""
    name: str | None = None
    agent_url: str
    ssh_host: str

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if value and not AGENT_ID_RE.match(value):
            raise ValueError("agent id must match [\\w.-]+")
        return value

    @field_validator("agent_url", "ssh_host")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.rstrip("/") if value.startswith(("http://", "https://")) else value

    @property
    def display_name(self) -> str:
        """Human readable name used by the Web UI."""
        return self.name or self.id


class DefaultsConfig(BaseModel):
    """Default create form values."""

    agent: str
    image: str
    user: str = shared.DEFAULT_CONTAINER_USER
    workspace: str = shared.DEFAULT_WORKSPACE
    extra_repos: list[str] = Field(default_factory=list)

    @field_validator("workspace")
    @classmethod
    def _check_workspace(cls, value: str) -> str:
        if not shared.WORKSPACE_RE.match(value):
            raise ValueError("workspace must match [\\w.-]+")
        return value

    @field_validator("extra_repos")
    @classmethod
    def _check_extra_repos(cls, value: list[str]) -> list[str]:
        for repo in value:
            if not shared.REPO_RE.match(repo):
                raise ValueError(f"extra repo must match 'owner/name': {repo!r}")
        return value

    @field_validator("agent", "image", "user")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class GithubConfig(BaseModel):
    """GitHub token lookup config."""

    token_env: str = "GITHUB_TOKEN"  # noqa: S105 - this is an env var name, not a token

    @field_validator("token_env")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class WebConfig(BaseModel):
    """Complete Web GUI configuration loaded from YAML."""

    defaults: DefaultsConfig
    github: GithubConfig = Field(default_factory=GithubConfig)
    agents: dict[str, AgentProfile]

    @model_validator(mode="before")
    @classmethod
    def _inject_agent_ids(cls, data: object) -> object:
        if not isinstance(data, dict) or not isinstance(data.get("agents"), dict):
            return data
        agents: dict[str, object] = {}
        for agent_id, raw_profile in data["agents"].items():
            profile = dict(raw_profile or {})
            profile.setdefault("id", agent_id)
            profile.setdefault("name", agent_id)
            agents[agent_id] = profile
        data = dict(data)
        data["agents"] = agents
        return data

    @model_validator(mode="after")
    def _validate_config(self) -> Self:
        if not self.agents:
            raise ValueError("at least one agent is required")
        for agent_id, profile in self.agents.items():
            if not AGENT_ID_RE.match(agent_id):
                raise ValueError(f"agent id must match [\\w.-]+: {agent_id!r}")
            if profile.id != agent_id:
                raise ValueError(f"agent profile id mismatch: {agent_id!r}")
        if self.defaults.agent not in self.agents:
            raise ValueError(f"defaults.agent {self.defaults.agent!r} not found in agents")
        return self


def resolve_config_path(path: str | Path | None = None) -> Path:
    """Resolve the YAML config path from explicit arg, env, or default path."""
    if path is not None:
        return Path(path).expanduser()
    configured = os.environ.get(CONFIG_ENV)
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_CONFIG_PATH


def load_config(path: str | Path | None = None) -> WebConfig:
    """Load and validate the Web GUI YAML config."""
    config_path = resolve_config_path(path)
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config file must be a YAML mapping")
    return WebConfig.model_validate(raw)


def github_token(config: WebConfig) -> str | None:
    """Return the configured GitHub token from the environment, if present."""
    return os.environ.get(config.github.token_env)
