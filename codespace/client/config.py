"""Strict startup configuration loaded from the fixed Codespace YAML path."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from codespace.client.compose import ServiceSpec
from codespace.client.models import (
    PODMAN_SOCKET,
    RESOURCE_ID_RE,
    GitProvider,
    HostId,
    ImagePlatform,
    NonBlankString,
    ProjectType,
    RepoPath,
    TokenString,
    parse_port_mapping,
    workspace_open_path,
)

CONFIG_PATH = Path.home() / ".config" / "codespace" / "config.yaml"

# Environment keys the control plane derives per container and therefore must
# not be supplied through the passthrough ``container.environment``; a collision
# is a configuration error rather than a silent override.
_RESERVED_ENV_KEYS = frozenset({"SSHD_PORT", "SSHD_BIND"})


def _reject_reserved_env(value: dict[str, str] | None) -> dict[str, str] | None:
    if value is None:
        return value
    reserved = _RESERVED_ENV_KEYS & value.keys()
    if reserved:
        raise ValueError(
            f"container.environment must not set control-plane keys {sorted(reserved)}"
        )
    return value


class ContainerConfig(ServiceSpec):
    """A ``container`` block: a Compose service plus control-plane guards.

    Inherits the all-optional Compose service subset and adds the control-plane
    rules that ``environment`` must not carry the keys the control plane derives
    itself, and that ``network_mode`` is restricted to the two modes the control
    plane knows how to wire (``host``/``bridge``). Because every field is
    optional, the same type serves as the global block and as per-host/per-project
    overrides layered on top of it (``merged_with``).
    """

    @field_validator("environment")
    @classmethod
    def _reject_reserved(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _reject_reserved_env(value)

    @field_validator("network_mode")
    @classmethod
    def _validate_network_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in ("host", "bridge"):
            raise ValueError("network_mode must be 'host' or 'bridge'")
        return value

    @property
    def is_bridge(self) -> bool:
        """Whether the resolved container uses a bridge network.

        Bridge containers get their own netns, so sshd must bind all interfaces
        and the SSH port plus any business ports are published; ``host``
        containers share the host netns instead.
        """
        return self.network_mode == "bridge"


class HostConfig(BaseModel):
    """Connection settings keyed by host ID in ``hosts``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["ssh", "podman-machine"] = "ssh"
    podman_socket: str | None = None
    machine: NonBlankString | None = None
    container: ContainerConfig | None = None

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
    type: ProjectType = "repo"
    provider: GitProvider | None = None
    repo: RepoPath | None = None
    description: NonBlankString | None = None
    image: NonBlankString | None = None
    platform: ImagePlatform | None = None
    open_path: NonBlankString | None = None
    published_ports: list[str] | None = None
    container: ContainerConfig | None = None

    @field_validator("open_path")
    @classmethod
    def _validate_open_path(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("open_path must be an absolute path")
        return value

    @field_validator("published_ports")
    @classmethod
    def _validate_published_ports(cls, value: list[str] | None) -> list[str] | None:
        """Reject malformed port specs and duplicate host bindings at load time."""
        if value is None:
            return value
        seen_local: set[int] = set()
        for spec in value:
            local, _remote = parse_port_mapping(spec)
            if local in seen_local:
                raise ValueError(f"duplicate published host port {local}")
            seen_local.add(local)
        return value

    @model_validator(mode="before")
    @classmethod
    def _split_provider_repo(cls, data: object) -> object:
        """Split the combined ``repo: <provider>:<owner>/<name>`` form.

        Accepts either the combined form or an already-split mapping (as
        produced by ``model_dump``); the two are unambiguous because a repo
        path never contains a colon.
        """
        if isinstance(data, dict) and isinstance(data.get("repo"), str) and ":" in data["repo"]:
            if "provider" in data:
                raise ValueError("set either combined 'repo' or separate 'provider', not both")
            provider, _, repo = data["repo"].partition(":")
            return {**data, "provider": provider, "repo": repo}
        return data

    @model_validator(mode="after")
    def _validate_type_fields(self) -> Self:
        if self.type == "repo":
            if self.repo is None or self.provider is None:
                raise ValueError("repo project requires 'repo' and 'provider'")
            return self
        if self.repo is not None or self.provider is not None:
            raise ValueError("blank project must not set 'repo' or 'provider'")
        return self

    def resolved_open_path(self) -> str:
        """Return the editor open path, defaulting per project type."""
        return self.open_path or workspace_open_path(self.repo)


class Config(BaseModel):
    """Complete immutable Codespace configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_image: NonBlankString
    container: ContainerConfig = Field(default_factory=ContainerConfig)
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
            resolved = self.resolved_container(project_id)
            if resolved.network_mode is None:
                raise ValueError(
                    f"project {project_id!r} has no resolved container.network_mode; set it on "
                    "the global, host, or project container block"
                )
            if project.published_ports and not resolved.is_bridge:
                raise ValueError(
                    f"project {project_id!r} sets 'published_ports' but its resolved "
                    "container.network_mode is not 'bridge'; port publishing requires bridge mode"
                )
        return self

    def project_image(self, project_id: str) -> str:
        """Resolve a project image against the required default image."""
        return self.projects[project_id].image or self.default_image

    def project_open_path(self, project_id: str) -> str:
        """Resolve one project's editor open path, defaulting per type."""
        return self.projects[project_id].resolved_open_path()

    def project_ports(self, project_id: str) -> list[tuple[int, int]]:
        """Resolve one project's published ``(local, remote)`` port mappings."""
        ports = self.projects[project_id].published_ports
        if not ports:
            return []
        return [parse_port_mapping(spec) for spec in ports]

    def resolved_container(self, project_id: str) -> ContainerConfig:
        """Resolve one project's container run flags across the override layers.

        Applies host then project overrides on top of the global ``container``
        block. The layering semantics (shallow, key-level replace; precedence
        ``project > host > global``) live in ``ServiceSpec.merged_with``.
        """
        project = self.projects[project_id]
        return self.container.merged_with(
            self.hosts[project.host].container,
            project.container,
        )

    def seed_tokens(self) -> dict[GitProvider, str]:
        """Return provider tokens declared in ``tokens`` to seed the store."""
        seeded: dict[GitProvider, str] = {}
        if self.tokens.github is not None:
            seeded["github"] = self.tokens.github
        if self.tokens.gitlab is not None:
            seeded["gitlab"] = self.tokens.gitlab
        return seeded

    def host_config(self, host: str) -> HostConfig:
        """Return one host's connection settings."""
        return self.hosts[host]


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read and validate the fixed-format YAML configuration."""
    with path.open("rb") as config_file:
        raw = yaml.safe_load(config_file)
    return Config.model_validate(raw)
