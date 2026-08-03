"""Strict startup configuration loaded from the fixed Codespace YAML path."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from codespace.client.models import (
    PODMAN_SOCKET,
    RESOURCE_ID_RE,
    GitProvider,
    HostId,
    ImagePlatform,
    NonBlankString,
    RepoPath,
    TokenString,
)

CONFIG_PATH = Path.home() / ".config" / "codespace" / "config.yaml"


class HostConfig(BaseModel):
    """Connection settings keyed by host ID in ``hosts``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["ssh", "podman-machine"] = "ssh"
    podman_socket: str | None = None
    machine: NonBlankString | None = None

    @field_validator("podman_socket")
    @classmethod
    def _validate_podman_socket(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("podman_socket must be an absolute path")
        return value

    @model_validator(mode="after")
    def _validate_type_fields(self) -> Self:
        if self.type == "ssh":
            if self.machine is not None:
                raise ValueError("machine is only valid for podman-machine hosts")
            return self
        if self.machine is None:
            raise ValueError("machine is required for podman-machine hosts")
        if self.podman_socket is not None:
            raise ValueError("podman_socket is not valid for podman-machine hosts")
        return self

    def resolved_podman_socket(self) -> str:
        """Return the remote socket used by an SSH host."""
        if self.type != "ssh":
            raise ValueError("podman-machine socket is discovered from machine inspect")
        return self.podman_socket or PODMAN_SOCKET


class TokensConfig(BaseModel):
    """Optional provider tokens read from the local ``[tokens]`` table.

    Tokens supplied here seed the in-memory token store at startup so the
    control plane does not require re-entering them through the Web UI after a
    restart. They are secrets stored in plaintext on the local config file.
    """

    model_config = ConfigDict(extra="forbid")

    github: TokenString | None = Field(default=None, repr=False)
    gitlab: TokenString | None = Field(default=None, repr=False)


class ProjectConfig(BaseModel):
    """Configuration for one project and its target host."""

    model_config = ConfigDict(extra="forbid")

    host: HostId
    provider: GitProvider
    repo: RepoPath
    description: NonBlankString | None = None
    image: NonBlankString | None = None
    platform: ImagePlatform | None = None


class Config(BaseModel):
    """Complete immutable Codespace configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_image: NonBlankString
    hosts: dict[HostId, HostConfig]
    projects: dict[str, ProjectConfig]
    tokens: TokensConfig = Field(default_factory=TokensConfig, repr=False)

    @field_validator("hosts", mode="before")
    @classmethod
    def _default_host_options(cls, value: object) -> object:
        """Treat a host declared with no options (``null``) as default SSH settings."""
        if isinstance(value, dict):
            return {host: options if options is not None else {} for host, options in value.items()}
        return value

    @field_validator("hosts")
    @classmethod
    def _validate_hosts(cls, value: dict[HostId, HostConfig]) -> dict[HostId, HostConfig]:
        if not value:
            raise ValueError("hosts must contain at least one host")
        return value

    @model_validator(mode="after")
    def _validate_projects(self) -> Self:
        if not self.projects:
            raise ValueError("projects must contain at least one project")
        for project_id, project in self.projects.items():
            if not RESOURCE_ID_RE.fullmatch(project_id):
                raise ValueError(f"project {project_id!r} must match ^[a-z0-9][a-z0-9-]{{0,31}}$")
            if project.host not in self.hosts:
                raise ValueError(f"project {project_id!r} references unknown host {project.host!r}")
        return self

    def project_image(self, project_id: str) -> str:
        """Resolve a project image against the required default image."""
        return self.projects[project_id].image or self.default_image

    def seed_tokens(self) -> dict[GitProvider, str]:
        """Return provider tokens declared in ``tokens`` to seed the store."""
        seeded: dict[GitProvider, str] = {}
        if self.tokens.github is not None:
            seeded["github"] = self.tokens.github
        if self.tokens.gitlab is not None:
            seeded["gitlab"] = self.tokens.gitlab
        return seeded

    def podman_socket(self, host: str) -> str:
        """Resolve one host's remote Podman socket, defaulting to the standard path."""
        return self.host_config(host).resolved_podman_socket()

    def host_config(self, host: str) -> HostConfig:
        """Return one host's connection settings."""
        return self.hosts[host]

    def host_configs(self) -> dict[str, HostConfig]:
        """Map every configured host to its resolved connection settings."""
        return dict(self.hosts)


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read and validate the fixed-format YAML configuration."""
    with path.open("rb") as config_file:
        raw = yaml.safe_load(config_file)
    return Config.model_validate(raw)
