"""Single-file configuration schema and placement resolution."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from codespace.runtime.container import ContainerSpec, ImagePlatform, NonBlankString
from codespace.runtime.transport import HostEndpoint
from codespace.services.models import SERVICE_DATA_PLACEHOLDER, ServiceSpec
from codespace.workspaces.models import (
    CACHE_MOUNT,
    CHECKOUT_PATH_ENV,
    CLONE_URL_ENV,
    CONTROL_MOUNT,
    HOME_CACHE_MOUNTS,
    OPEN_PATH_ENV,
    SOURCE_TYPE_ENV,
    SSHD_BIND_ENV,
    SSHD_PORT_ENV,
    UPLOAD_MOUNT,
    WORKSPACE_CIPHER_MOUNT,
    WORKSPACE_KEY_ENV,
    WORKSPACE_KEY_SECRET,
    WORKSPACE_MOUNT,
    GitProvider,
    GitUrl,
    HostId,
    RepositoryPath,
    ResourceId,
    TokenString,
    WorkspaceSpec,
)

CONFIG_PATH = Path.home() / ".config" / "codespace" / "config.yaml"
_ENVIRONMENT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_ENVIRONMENT = {
    SOURCE_TYPE_ENV,
    CLONE_URL_ENV,
    CHECKOUT_PATH_ENV,
    OPEN_PATH_ENV,
    WORKSPACE_KEY_ENV,
    SSHD_PORT_ENV,
    SSHD_BIND_ENV,
}
_RESERVED_MOUNTS = (
    WORKSPACE_MOUNT,
    WORKSPACE_CIPHER_MOUNT,
    UPLOAD_MOUNT,
    CACHE_MOUNT,
    CONTROL_MOUNT,
    *(target for _name, target in HOME_CACHE_MOUNTS),
)


def _environment_name(value: str) -> str:
    if not _ENVIRONMENT_NAME_RE.fullmatch(value):
        raise ValueError("must be a valid environment variable name")
    return value


def _workspace_path(value: str) -> str:
    path = PurePosixPath(value)
    workspace = PurePosixPath(WORKSPACE_MOUNT)
    if not path.is_absolute() or (path != workspace and workspace not in path.parents):
        raise ValueError(f"must be {WORKSPACE_MOUNT} or a path below it")
    return str(path)


type EnvironmentName = Annotated[str, AfterValidator(_environment_name)]
type WorkspacePath = Annotated[str, AfterValidator(_workspace_path)]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HostConfig(FrozenModel):
    """SSH and Podman connection settings for one Host."""

    podman_socket: str | None = None
    forward_environment: list[EnvironmentName] = Field(default_factory=list)

    def endpoint(self) -> HostEndpoint:
        return HostEndpoint(podman_socket=self.podman_socket)


class ProviderSource(FrozenModel):
    type: GitProvider
    repository: RepositoryPath

    @property
    def clone_url(self) -> str:
        host = "github.com" if self.type == "github" else "gitlab.com"
        return f"git@{host}:{self.repository}.git"

    @property
    def checkout_name(self) -> str:
        return self.repository.rsplit("/", 1)[-1].removesuffix(".git")


class GitSource(FrozenModel):
    type: Literal["git"]
    url: GitUrl

    @property
    def clone_url(self) -> str:
        return self.url

    @property
    def checkout_name(self) -> str:
        trimmed = self.url.rstrip("/").removesuffix(".git")
        return re.split(r"[/:]", trimmed)[-1]


class EmptySource(FrozenModel):
    type: Literal["empty"]

    @property
    def clone_url(self) -> None:
        return None

    @property
    def checkout_name(self) -> None:
        return None


type ProjectSource = Annotated[
    ProviderSource | GitSource | EmptySource, Field(discriminator="type")
]


class ProjectPlacement(FrozenModel):
    """Overrides applied after Project defaults and Project fields."""

    platform: ImagePlatform | None = None
    image: NonBlankString | None = None
    container: ContainerSpec | None = None


class ProjectDefaults(FrozenModel):
    image: NonBlankString
    container: ContainerSpec = Field(default_factory=ContainerSpec)


class ProjectConfig(FrozenModel):
    description: NonBlankString | None = None
    source: ProjectSource
    hosts: dict[HostId, ProjectPlacement] = Field(min_length=1)
    image: NonBlankString | None = None
    checkout_path: WorkspacePath | None = None
    open_path: WorkspacePath | None = None
    encrypted: bool = False
    container: ContainerSpec | None = None

    def resolved_checkout_path(self) -> str:
        if self.checkout_path is not None:
            return self.checkout_path
        name = self.source.checkout_name
        return WORKSPACE_MOUNT if name is None else f"{WORKSPACE_MOUNT}/{name}"

    def resolved_open_path(self) -> str:
        return self.open_path or self.resolved_checkout_path()


class ServicePlacement(FrozenModel):
    """Overrides applied after the Service's base configuration."""

    image: NonBlankString | None = None
    container: ContainerSpec | None = None


class ServiceConfig(FrozenModel):
    image: NonBlankString
    hosts: dict[HostId, ServicePlacement] = Field(min_length=1)
    container: ContainerSpec = Field(default_factory=ContainerSpec)


class TokensConfig(FrozenModel):
    github: TokenString | None = Field(default=None, repr=False)
    gitlab: TokenString | None = Field(default=None, repr=False)


class Config(FrozenModel):
    """Complete immutable Codespace configuration."""

    hosts: dict[HostId, HostConfig] = Field(min_length=1)
    project_defaults: ProjectDefaults
    projects: dict[ResourceId, ProjectConfig] = Field(default_factory=dict)
    services: dict[ResourceId, ServiceConfig] = Field(default_factory=dict)
    tokens: TokensConfig = Field(default_factory=TokensConfig, repr=False)
    secrets: dict[NonBlankString, NonBlankString] = Field(default_factory=dict, repr=False)

    @model_validator(mode="after")
    def _validate_contracts(self) -> Config:
        for project_id, project in self.projects.items():
            for host in project.hosts:
                if host not in self.hosts:
                    raise ValueError(f"project {project_id!r} references unknown host {host!r}")
                self._validate_project_container(
                    project_id,
                    host,
                    self.resolved_project_container(project_id, host),
                )
            if project.encrypted and WORKSPACE_KEY_SECRET not in self.secrets:
                raise ValueError(
                    f"encrypted project {project_id!r} requires secret {WORKSPACE_KEY_SECRET!r}"
                )
        for service_id, service in self.services.items():
            for host in service.hosts:
                if host not in self.hosts:
                    raise ValueError(f"service {service_id!r} references unknown host {host!r}")
                self._validate_service_container(
                    service_id,
                    host,
                    self.resolved_service_container(service_id, host),
                )
        return self

    def project_hosts(self, project: str) -> list[str]:
        return list(self.projects[project].hosts)

    def service_hosts(self, service: str) -> list[str]:
        return list(self.services[service].hosts)

    def resolved_project_container(self, project: str, host: str) -> ContainerSpec:
        configured = self.projects[project]
        placement = configured.hosts[host]
        return self.project_defaults.container.merged_with(
            configured.container,
            placement.container,
        )

    def resolved_service_container(self, service: str, host: str) -> ContainerSpec:
        configured = self.services[service]
        return configured.container.merged_with(configured.hosts[host].container)

    def project_image(self, project: str, host: str) -> str:
        configured = self.projects[project]
        placement = configured.hosts[host]
        return placement.image or configured.image or self.project_defaults.image

    def service_image(self, service: str, host: str) -> str:
        configured = self.services[service]
        return configured.hosts[host].image or configured.image

    def workspace_spec(self, project: str, host: str, workspace: str) -> WorkspaceSpec:
        configured = self.projects[project]
        placement = configured.hosts[host]
        source = configured.source
        return WorkspaceSpec(
            project=project,
            workspace=workspace,
            host=host,
            source=source.type,
            repository=source.repository if isinstance(source, ProviderSource) else None,
            git_url=source.url if isinstance(source, GitSource) else None,
            clone_url=source.clone_url,
            platform=placement.platform,
            image=self.project_image(project, host),
            container=self.resolved_project_container(project, host),
            checkout_path=configured.resolved_checkout_path(),
            open_path=configured.resolved_open_path(),
            encrypted=configured.encrypted,
        )

    def service_spec(self, service: str, host: str) -> ServiceSpec:
        return ServiceSpec(
            service=service,
            host=host,
            image=self.service_image(service, host),
            container=self.resolved_service_container(service, host),
        )

    def seed_tokens(self) -> dict[GitProvider, str]:
        tokens: dict[GitProvider, str] = {}
        if self.tokens.github is not None:
            tokens["github"] = self.tokens.github
        if self.tokens.gitlab is not None:
            tokens["gitlab"] = self.tokens.gitlab
        return tokens

    @staticmethod
    def _validate_network(resource: str, host: str, container: ContainerSpec) -> None:
        if container.network_mode is None:
            raise ValueError(f"{resource} on host {host!r} must resolve network_mode")
        if container.ports and not container.is_bridge:
            raise ValueError(f"{resource} on host {host!r} may publish ports only in bridge mode")

    @classmethod
    def _validate_project_container(
        cls,
        project: str,
        host: str,
        container: ContainerSpec,
    ) -> None:
        cls._validate_network(f"project {project!r}", host, container)
        reserved_environment = _RESERVED_ENVIRONMENT.intersection(container.environment or {})
        if reserved_environment:
            names = ", ".join(sorted(reserved_environment))
            raise ValueError(f"project {project!r} overrides reserved environment: {names}")
        for name, volume in (container.volumes or {}).items():
            if volume.source.startswith("${"):
                raise ValueError(f"project volume {name!r} must use an absolute source")
            if any(_paths_overlap(volume.target, reserved) for reserved in _RESERVED_MOUNTS):
                raise ValueError(
                    f"project volume {name!r} overlaps reserved target {volume.target!r}"
                )
        for name, secret in (container.secrets or {}).items():
            if secret.mode == "env" and secret.target in _RESERVED_ENVIRONMENT:
                raise ValueError(f"project secret {name!r} overrides reserved environment")
            if (
                secret.mode == "mount"
                and secret.target is not None
                and any(_paths_overlap(secret.target, reserved) for reserved in _RESERVED_MOUNTS)
            ):
                raise ValueError(f"project secret {name!r} overlaps a reserved mount target")

    @classmethod
    def _validate_service_container(
        cls,
        service: str,
        host: str,
        container: ContainerSpec,
    ) -> None:
        cls._validate_network(f"service {service!r}", host, container)
        for name, volume in (container.volumes or {}).items():
            if volume.source.startswith("${") and volume.source != SERVICE_DATA_PLACEHOLDER:
                raise ValueError(
                    f"service volume {name!r} uses unknown placeholder {volume.source!r}"
                )


def _paths_overlap(left: str, right: str) -> bool:
    left_path = PurePosixPath(left)
    right_path = PurePosixPath(right)
    return (
        left_path == right_path
        or left_path in right_path.parents
        or right_path in left_path.parents
    )


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read and validate the one canonical YAML configuration file."""
    with path.open("rb") as config_file:
        raw = yaml.safe_load(config_file) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config {path.resolve()} must be a mapping")
    return Config.model_validate(raw)
