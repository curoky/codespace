"""Strict startup configuration loaded from the fixed Codespace TOML path."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from codespace.client.models import (
    HOST_RE,
    PODMAN_SOCKET,
    REPO_RE,
    RESOURCE_ID_RE,
    GitProvider,
)

CONFIG_PATH = Path.home() / ".config" / "codespace" / "config.toml"


class HostConfig(BaseModel):
    """Optional per-host overrides keyed by SSH alias in ``host_options``."""

    model_config = ConfigDict(extra="forbid")

    podman_socket: str = PODMAN_SOCKET

    @field_validator("podman_socket")
    @classmethod
    def _validate_podman_socket(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("podman_socket must be an absolute path")
        return value


class TokensConfig(BaseModel):
    """Optional provider tokens read from the local ``[tokens]`` table.

    Tokens supplied here seed the in-memory token store at startup so the
    control plane does not require re-entering them through the Web UI after a
    restart. They are secrets stored in plaintext on the local config file.
    """

    model_config = ConfigDict(extra="forbid")

    github: str | None = Field(default=None, repr=False)
    gitlab: str | None = Field(default=None, repr=False)

    @field_validator("github", "gitlab")
    @classmethod
    def _not_blank_optional(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("token must not be blank")
        return value


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
    host_options: dict[str, HostConfig] = Field(default_factory=dict)
    tokens: TokensConfig = Field(default_factory=TokensConfig, repr=False)

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
        for host in self.host_options:
            if host not in configured_hosts:
                raise ValueError(f"host_options references unknown host {host!r}")
        return self

    def project_image(self, project_id: str) -> str:
        """Resolve a project image against the required default image."""
        return self.projects[project_id].image or self.default_image

    def seed_tokens(self) -> dict[GitProvider, str]:
        """Return provider tokens declared in ``[tokens]`` to seed the store."""
        seeded: dict[GitProvider, str] = {}
        if self.tokens.github is not None:
            seeded["github"] = self.tokens.github
        if self.tokens.gitlab is not None:
            seeded["gitlab"] = self.tokens.gitlab
        return seeded

    def podman_socket(self, host: str) -> str:
        """Resolve one host's remote Podman socket, defaulting to the standard path."""
        options = self.host_options.get(host)
        return options.podman_socket if options is not None else PODMAN_SOCKET

    def podman_sockets(self) -> dict[str, str]:
        """Map every configured host to its remote Podman socket path."""
        return {host: self.podman_socket(host) for host in self.hosts}


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read and validate the fixed-format TOML configuration."""
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return Config.model_validate(raw)
