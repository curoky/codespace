"""Strict startup configuration loaded from the fixed Codespace TOML path."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from codespace.models import HOST_RE, REPO_RE, RESOURCE_ID_RE, GitProvider

CONFIG_PATH = Path.home() / ".config" / "codespace" / "config.toml"


class ProjectConfig(BaseModel):
    """Configuration for one project and its target host."""

    model_config = ConfigDict(extra="forbid")

    host: str
    provider: GitProvider
    repo: str
    description: str | None = None
    image: str | None = None

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: str) -> str:
        if not HOST_RE.fullmatch(value):
            raise ValueError("host must match ^[a-z0-9][a-z0-9.-]{0,62}$")
        return value

    @field_validator("repo")
    @classmethod
    def _validate_repo(cls, value: str) -> str:
        if not REPO_RE.fullmatch(value):
            raise ValueError("repo must be a slash-separated path like 'owner/name'")
        return value

    @field_validator("description", "image")
    @classmethod
    def _not_blank_optional(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class Config(BaseModel):
    """Complete immutable Codespace configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_image: str
    hosts: list[str]
    projects: dict[str, ProjectConfig]

    @field_validator("default_image")
    @classmethod
    def _validate_default_image(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("default_image must not be blank")
        return value

    @field_validator("hosts")
    @classmethod
    def _validate_hosts(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("hosts must contain at least one host")
        if len(value) != len(set(value)):
            raise ValueError("hosts must not contain duplicates")
        for host in value:
            if not HOST_RE.fullmatch(host):
                raise ValueError(f"host {host!r} must match ^[a-z0-9][a-z0-9.-]{{0,62}}$")
        return value

    @model_validator(mode="after")
    def _validate_projects(self) -> Self:
        if not self.projects:
            raise ValueError("projects must contain at least one project")
        configured_hosts = set(self.hosts)
        for project_id, project in self.projects.items():
            if not RESOURCE_ID_RE.fullmatch(project_id):
                raise ValueError(f"project {project_id!r} must match ^[a-z0-9][a-z0-9-]{{0,31}}$")
            if project.host not in configured_hosts:
                raise ValueError(f"project {project_id!r} references unknown host {project.host!r}")
        return self

    def project_image(self, project_id: str) -> str:
        """Resolve a project image against the required default image."""
        return self.projects[project_id].image or self.default_image


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read and validate the fixed-format TOML configuration."""
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return Config.model_validate(raw)
