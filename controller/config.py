"""Strict startup configuration loaded from the fixed Codespace YAML path."""

from __future__ import annotations

import posixpath
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from controller.compose import Secret, ServiceSpec, Volume
from controller.models import (
    PODMAN_SOCKET,
    RESOURCE_ID_RE,
    WORKSPACE_MOUNT,
    EnvironmentSpec,
    GitProvider,
    GitUrl,
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

# Derived per container and forbidden in passthrough environment values.
_RESERVED_ENV_KEYS = frozenset({"SSHD_PORT", "SSHD_BIND"})
_RESERVED_MOUNT_TARGETS = ("/workspace", "/upload")
type EnvironmentName = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]


def _require_under_workspace(value: PurePosixPath) -> PurePosixPath:
    """Require a POSIX path strictly under the reserved workspace mount, without ``..``."""
    if ".." in value.parts:
        raise ValueError("path must not contain '..' segments")
    if PurePosixPath(WORKSPACE_MOUNT) not in value.parents:
        raise ValueError(f"path must be a directory under {WORKSPACE_MOUNT}")
    return value


# A container checkout directory: an absolute path strictly under ``/workspace``.
type WorkspacePath = Annotated[PurePosixPath, AfterValidator(_require_under_workspace)]


def _reject_reserved_env(value: dict[str, str] | None) -> dict[str, str] | None:
    if value is None:
        return value
    reserved = _RESERVED_ENV_KEYS & value.keys()
    if reserved:
        raise ValueError(
            f"container.environment must not set control-plane keys {sorted(reserved)}"
        )
    return value


def _env_secret_targets(secrets: list[Secret] | None) -> list[str]:
    """Return the environment variable names produced by ``mode: env`` secrets."""
    if secrets is None:
        return []
    return [secret.target for secret in secrets if secret.mode == "env" and secret.target]


def _mount_targets_overlap(left: str, right: str) -> bool:
    normalized_left = "/" + posixpath.normpath(left).lstrip("/")
    normalized_right = "/" + posixpath.normpath(right).lstrip("/")
    common = posixpath.commonpath((normalized_left, normalized_right))
    return common in (normalized_left, normalized_right)


class ContainerConfig(ServiceSpec):
    """Compose service subset with Codespace-specific validation."""

    @field_validator("environment")
    @classmethod
    def _reject_reserved(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        return _reject_reserved_env(value)

    @field_validator("volumes")
    @classmethod
    def _reject_reserved_mount_targets(
        cls,
        value: list[Volume] | None,
    ) -> list[Volume] | None:
        if value is None:
            return value
        conflicts = sorted(
            {
                volume.target
                for volume in value
                if any(
                    _mount_targets_overlap(volume.target, reserved)
                    for reserved in _RESERVED_MOUNT_TARGETS
                )
            }
        )
        if conflicts:
            raise ValueError(
                "container.volumes must not overlap control-plane mount targets "
                f"{list(_RESERVED_MOUNT_TARGETS)}: {conflicts}"
            )
        return value

    @field_validator("network_mode")
    @classmethod
    def _validate_network_mode(cls, value: str | None) -> str | None:
        if value is not None and value not in ("host", "bridge"):
            raise ValueError("network_mode must be 'host' or 'bridge'")
        return value

    @field_validator("secrets")
    @classmethod
    def _reject_reserved_secret_mount_targets(
        cls,
        value: list[Secret] | None,
    ) -> list[Secret] | None:
        if value is None:
            return value
        conflicts = sorted(
            {
                secret.target
                for secret in value
                if secret.mode == "mount"
                and secret.target is not None
                and any(
                    _mount_targets_overlap(secret.target, reserved)
                    for reserved in _RESERVED_MOUNT_TARGETS
                )
            }
        )
        if conflicts:
            raise ValueError(
                "container.secrets mount targets must not overlap control-plane mount targets "
                f"{list(_RESERVED_MOUNT_TARGETS)}: {conflicts}"
            )
        return value

    @model_validator(mode="after")
    def _validate_env_secret_targets(self) -> Self:
        """Env-mode secrets share the container environment namespace."""
        targets = _env_secret_targets(self.secrets)
        reserved = _RESERVED_ENV_KEYS & set(targets)
        if reserved:
            raise ValueError(
                f"container.secrets env target must not use control-plane keys {sorted(reserved)}"
            )
        duplicates = sorted({name for name in targets if targets.count(name) > 1})
        if duplicates:
            raise ValueError(f"container.secrets env target must not repeat names: {duplicates}")
        explicit = set(self.environment or {})
        collisions = sorted(explicit & set(targets))
        if collisions:
            raise ValueError(
                f"container.secrets env target collides with container.environment: {collisions}"
            )
        return self

    @property
    def is_bridge(self) -> bool:
        return self.network_mode == "bridge"


class HostConfig(BaseModel):
    """Connection settings keyed by host ID in ``hosts``."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["ssh", "podman-machine"] = "ssh"
    podman_socket: str | None = None
    machine: NonBlankString | None = None
    environment: list[EnvironmentName] = Field(default_factory=list)
    container: ContainerConfig | None = None

    @field_validator("podman_socket")
    @classmethod
    def _validate_podman_socket(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("podman_socket must be an absolute path")
        return value

    @field_validator("environment")
    @classmethod
    def _validate_environment(cls, value: list[str]) -> list[str]:
        duplicates = sorted({name for name in value if value.count(name) > 1})
        if duplicates:
            raise ValueError(f"environment must not contain duplicates: {duplicates}")
        reserved = _RESERVED_ENV_KEYS & set(value)
        if reserved:
            raise ValueError(f"environment must not inherit control-plane keys {sorted(reserved)}")
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
        if self.environment:
            raise ValueError("environment is only valid for SSH hosts")
        return self

    def resolved_podman_socket(self) -> str:
        """Return the remote socket used by an SSH host."""
        if self.type != "ssh":
            raise ValueError("podman-machine socket is discovered from machine inspect")
        return self.podman_socket or PODMAN_SOCKET


class TokensConfig(BaseModel):
    """Optional startup values for the process-local token store."""

    model_config = ConfigDict(extra="forbid")

    github: TokenString | None = Field(default=None, repr=False)
    gitlab: TokenString | None = Field(default=None, repr=False)


class ProjectHost(BaseModel):
    """One target host for a project with its per-host image platform."""

    model_config = ConfigDict(extra="forbid")

    name: HostId
    platform: ImagePlatform | None = None


class ProjectConfig(BaseModel):
    """Configuration for one project and the hosts it can run on."""

    model_config = ConfigDict(extra="forbid")

    host: list[ProjectHost]
    type: ProjectType = "repo"
    provider: GitProvider | None = None
    repo: RepoPath | None = None
    git_url: GitUrl | None = None
    description: NonBlankString | None = None
    image: NonBlankString | None = None
    open_path: NonBlankString | None = None
    clone_path: WorkspacePath | None = None
    published_ports: list[str] | None = None
    container: ContainerConfig | None = None

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: list[ProjectHost]) -> list[ProjectHost]:
        if not value:
            raise ValueError("host must list at least one target host")
        duplicates = sorted({e.name for e in value if [x.name for x in value].count(e.name) > 1})
        if duplicates:
            raise ValueError(f"host must not list a host more than once: {duplicates}")
        return value

    def host_platform(self, host: str) -> ImagePlatform | None:
        """Return the configured image platform for one of the project's hosts."""
        for entry in self.host:
            if entry.name == host:
                return entry.platform
        raise KeyError(f"project has no host {host!r}")

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
        """Split ``repo: <provider>:<owner>/<name>`` (or ``repo: git:<url>``) before validation."""
        if isinstance(data, dict) and isinstance(data.get("repo"), str) and ":" in data["repo"]:
            provider, _, rest = data["repo"].partition(":")
            if provider == "git":
                if "git_url" in data:
                    raise ValueError("set either combined 'repo' or separate 'git_url', not both")
                return {**data, "type": "git", "git_url": rest, "repo": None}
            if "provider" in data:
                raise ValueError("set either combined 'repo' or separate 'provider', not both")
            return {**data, "provider": provider, "repo": rest}
        return data

    @model_validator(mode="after")
    def _validate_type_fields(self) -> Self:
        if self.type == "repo":
            if self.repo is None or self.provider is None:
                raise ValueError("repo project requires 'repo' and 'provider'")
            if self.git_url is not None:
                raise ValueError("repo project must not set 'git_url'")
            return self
        if self.type == "git":
            if self.git_url is None:
                raise ValueError("git project requires 'git_url'")
            if self.repo is not None or self.provider is not None:
                raise ValueError("git project must not set 'repo' or 'provider'")
            return self
        if self.repo is not None or self.provider is not None or self.git_url is not None:
            raise ValueError("blank project must not set 'repo', 'provider' or 'git_url'")
        if self.clone_path is not None:
            raise ValueError("blank project must not set 'clone_path'")
        return self

    def resolved_clone_path(self) -> str:
        """Return the checkout directory, defaulting to the workspace-derived target."""
        if self.clone_path is not None:
            return str(self.clone_path)
        return workspace_open_path(self.repo, self.git_url)

    def resolved_open_path(self) -> str:
        """Return the editor open path, defaulting to the checkout directory."""
        return self.open_path or self.resolved_clone_path()


class Config(BaseModel):
    """Complete immutable Codespace configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_image: NonBlankString
    container: ContainerConfig = Field(default_factory=ContainerConfig)
    hosts: dict[HostId, HostConfig]
    projects: dict[str, ProjectConfig]
    tokens: TokensConfig = Field(default_factory=TokensConfig, repr=False)
    secrets: dict[NonBlankString, NonBlankString] = Field(default_factory=dict, repr=False)

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
            for entry in project.host:
                if entry.name not in self.hosts:
                    raise ValueError(
                        f"project {project_id!r} references unknown host {entry.name!r}"
                    )
                resolved = self.resolved_container(project_id, entry.name)
                if resolved.network_mode is None:
                    raise ValueError(
                        f"project {project_id!r} on host {entry.name!r} has no resolved "
                        "container.network_mode; set it on the global, host, or project "
                        "container block"
                    )
                if project.published_ports and not resolved.is_bridge:
                    raise ValueError(
                        f"project {project_id!r} sets 'published_ports' but its resolved "
                        f"container.network_mode on host {entry.name!r} is not 'bridge'; "
                        "port publishing requires bridge mode"
                    )
                inherited = set(self.hosts[entry.name].environment)
                explicit = set(resolved.environment or {})
                collisions = sorted(inherited & explicit)
                if collisions:
                    raise ValueError(
                        f"project {project_id!r} on host {entry.name!r} configures inherited "
                        f"host environment variables {collisions} in container.environment"
                    )
                secret_env = set(_env_secret_targets(resolved.secrets))
                secret_collisions = sorted(inherited & secret_env)
                if secret_collisions:
                    raise ValueError(
                        f"project {project_id!r} on host {entry.name!r} configures inherited "
                        f"host environment variables {secret_collisions} as container.secrets "
                        "env target"
                    )
        return self

    def project_image(self, project_id: str) -> str:
        """Resolve a project image against the required default image."""
        return self.projects[project_id].image or self.default_image

    def project_open_path(self, project_id: str) -> str:
        """Resolve one project's editor open path, defaulting per type."""
        return self.projects[project_id].resolved_open_path()

    def project_clone_path(self, project_id: str) -> str:
        """Resolve one project's checkout directory, defaulting per type."""
        return self.projects[project_id].resolved_clone_path()

    def project_ports(self, project_id: str) -> list[tuple[int, int]]:
        """Resolve one project's published ``(local, remote)`` port mappings."""
        ports = self.projects[project_id].published_ports
        if not ports:
            return []
        return [parse_port_mapping(spec) for spec in ports]

    def resolved_container(self, project_id: str, host: str) -> ContainerConfig:
        """Apply global, host and project container layers in order for one host."""
        project = self.projects[project_id]
        return self.container.merged_with(
            self.hosts[host].container,
            project.container,
        )

    def environment_spec(self, project_id: str, host: str, instance: str) -> EnvironmentSpec:
        """Resolve all configured inputs for one project instance on one host."""
        project = self.projects[project_id]
        return EnvironmentSpec(
            project_id=project_id,
            instance=instance,
            host=host,
            platform=project.host_platform(host),
            project=project,
            image=self.project_image(project_id),
            container=self.resolved_container(project_id, host),
            published_ports=tuple(self.project_ports(project_id)),
            open_path=self.project_open_path(project_id),
            clone_path=self.project_clone_path(project_id),
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
