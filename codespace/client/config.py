"""Strict startup configuration loaded from the fixed Codespace TOML path."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal, Self

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

CONFIG_PATH = Path.home() / ".config" / "codespace" / "config.toml"


class HostConfig(BaseModel):
    """Connection settings keyed by host ID in ``host_options``."""

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
    hosts: list[HostId]
    projects: dict[str, ProjectConfig]
    host_options: dict[str, HostConfig] = Field(default_factory=dict)
    tokens: TokensConfig = Field(default_factory=TokensConfig, repr=False)

    @field_validator("hosts")
    @classmethod
    def _validate_hosts(cls, value: list[HostId]) -> list[HostId]:
        if not value:
            raise ValueError("hosts must contain at least one host")
        if len(value) != len(set(value)):
            raise ValueError("hosts must not contain duplicates")
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
        return self.host_config(host).resolved_podman_socket()

    def host_config(self, host: str) -> HostConfig:
        """Return one host's explicit settings or the default SSH settings."""
        return self.host_options.get(host, HostConfig())

    def host_configs(self) -> dict[str, HostConfig]:
        """Map every configured host to its resolved connection settings."""
        return {host: self.host_config(host) for host in self.hosts}


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read and validate the fixed-format TOML configuration."""
    with path.open("rb") as config_file:
        raw = tomllib.load(config_file)
    return Config.model_validate(raw)
