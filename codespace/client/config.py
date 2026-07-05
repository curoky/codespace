"""YAML configuration for the local Codespace Web GUI."""

import os
import re
from pathlib import Path
from typing import Self

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from codespace import shared

CONFIG_ENV = "CODESPACE_CONFIG"
DEFAULT_CONFIG_PATH = Path.home() / ".config" / "codespace" / "config.yaml"
AGENT_ID_RE = re.compile(r"^[\w.-]+$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TOKEN_VALUE_PREFIXES = ("github_pat_", "ghp_", "gho_", "ghu_", "ghs_", "ghr_", "glpat-", "glabpat-")


def _validate_token_env(value: str) -> str:
    stripped = value.strip()
    if not ENV_NAME_RE.match(stripped) or stripped.startswith(TOKEN_VALUE_PREFIXES):
        raise ValueError("token_env must be an environment variable name")
    return stripped


class AgentProfile(BaseModel):
    """One configured agent profile."""

    id: str = ""
    agent_url: str
    ssh_host: str
    ssh_proxy_host: str | None = None
    ssh_proxy: bool = False

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if value and not AGENT_ID_RE.match(value):
            raise ValueError("agent id must match [\\w.-]+")
        return value

    @field_validator("agent_url", "ssh_host", "ssh_proxy_host")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("must not be blank")
        return value.rstrip("/") if value.startswith(("http://", "https://")) else value

    @model_validator(mode="after")
    def _require_proxy_host(self) -> Self:
        if self.ssh_proxy and self.ssh_proxy_host is None:
            raise ValueError("ssh_proxy_host is required when ssh_proxy is true")
        return self


class DefaultsConfig(BaseModel):
    """Default create form values."""

    model_config = ConfigDict(extra="forbid")

    agent: str
    image: str

    @field_validator("agent", "image")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class CreateTemplateConfig(BaseModel):
    """One preconfigured Web GUI create template."""

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    description: str | None = None
    agent: str | None = None
    provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER
    repo: str
    git_ssh_host: str | None = None
    image: str | None = None

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if value and not AGENT_ID_RE.match(value):
            raise ValueError("template id must match [\\w.-]+")
        return value

    @field_validator("repo")
    @classmethod
    def _check_repo(cls, value: str) -> str:
        if not shared.REPO_RE.match(value):
            raise ValueError("repo must be a slash-separated path like 'owner/name'")
        return value

    @field_validator("git_ssh_host")
    @classmethod
    def _check_git_ssh_host(cls, value: str | None) -> str | None:
        if value is None:
            return value
        stripped = value.strip()
        if not stripped or "/" in stripped or ":" in stripped:
            raise ValueError("git_ssh_host must be a hostname")
        return stripped

    @field_validator("agent")
    @classmethod
    def _check_agent(cls, value: str | None) -> str | None:
        if value is not None and not AGENT_ID_RE.match(value):
            raise ValueError("agent must match [\\w.-]+")
        return value

    @field_validator("description", "image")
    @classmethod
    def _not_blank_optional(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class GithubConfig(BaseModel):
    """GitHub token lookup config."""

    token_env: str = "GITHUB_TOKEN"  # noqa: S105 - this is an env var name, not a token

    @field_validator("token_env")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _validate_token_env(value)


class GitlabConfig(BaseModel):
    """GitLab token/API lookup config."""

    token_env: str = "GITLAB_TOKEN"  # noqa: S105 - this is an env var name, not a token
    api_url: str = "https://gitlab.com"
    ssh_host: str = shared.DEFAULT_GITLAB_SSH_HOST

    @field_validator("token_env", "api_url", "ssh_host")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped.rstrip("/") if stripped.startswith(("http://", "https://")) else stripped

    @field_validator("token_env")
    @classmethod
    def _check_token_env(cls, value: str) -> str:
        return _validate_token_env(value)


class WebConfig(BaseModel):
    """Complete Web GUI configuration loaded from YAML."""

    defaults: DefaultsConfig
    github: GithubConfig = Field(default_factory=GithubConfig)
    gitlab: GitlabConfig = Field(default_factory=GitlabConfig)
    agents: dict[str, AgentProfile]
    templates: dict[str, CreateTemplateConfig] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _inject_agent_ids(cls, data: object) -> object:
        if not isinstance(data, dict) or not isinstance(data.get("agents"), dict):
            return data
        agents: dict[str, object] = {}
        for agent_id, raw_profile in data["agents"].items():
            profile = dict(raw_profile or {})
            profile.setdefault("id", agent_id)
            agents[agent_id] = profile
        data = dict(data)
        data["agents"] = agents
        if isinstance(data.get("templates"), dict):
            templates: dict[str, object] = {}
            for template_id, raw_template in data["templates"].items():
                template = dict(raw_template or {})
                template.setdefault("id", template_id)
                templates[template_id] = template
            data["templates"] = templates
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
        for template_id, template in self.templates.items():
            if not AGENT_ID_RE.match(template_id):
                raise ValueError(f"template id must match [\\w.-]+: {template_id!r}")
            if template.id != template_id:
                raise ValueError(f"template id mismatch: {template_id!r}")
            if template.agent is not None and template.agent not in self.agents:
                raise ValueError(f"template {template_id!r} references unknown agent")
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
