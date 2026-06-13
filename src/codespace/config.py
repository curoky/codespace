"""Single-file configuration schema and placement resolution."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Annotated

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from codespace.runtime.container import (
    ContainerSpec,
    ImagePlatform,
    NonBlankString,
)
from codespace.services.models import SERVICE_DATA_PLACEHOLDER, ServiceSpec
from codespace.workspaces.models import (
    CACHE_MOUNT,
    CHECKOUT_PATH_ENV,
    CLONE_URL_ENV,
    CONTAINER_HOME,
    CONTROL_MOUNT,
    ENCRYPTED_ENV,
    OPEN_PATH_ENV,
    SOURCE_TYPE_ENV,
    SSHD_BIND_ENV,
    SSHD_PORT_ENV,
    UPLOAD_MOUNT,
    WORKSPACE_CIPHER_MOUNT,
    WORKSPACE_KEY_MOUNT,
    WORKSPACE_KEY_SECRET,
    WORKSPACE_MOUNT,
    GitProvider,
    HostId,
    ResourceId,
    Source,
    TokenString,
    WorkspacePath,
    WorkspaceSpec,
    workspace_path,
)

CONFIG_PATH = Path("/Users/x/.config/codespace/config.yaml")
_ENVIRONMENT_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED_ENVIRONMENT = {
    SOURCE_TYPE_ENV,
    CLONE_URL_ENV,
    CHECKOUT_PATH_ENV,
    OPEN_PATH_ENV,
    ENCRYPTED_ENV,
    SSHD_PORT_ENV,
    SSHD_BIND_ENV,
}
_RESERVED_MOUNTS = (
    WORKSPACE_MOUNT,
    WORKSPACE_CIPHER_MOUNT,
    UPLOAD_MOUNT,
    CACHE_MOUNT,
    CONTROL_MOUNT,
    WORKSPACE_KEY_MOUNT,
    CONTAINER_HOME,
)


def _environment_name(value: str) -> str:
    if not _ENVIRONMENT_NAME_RE.fullmatch(value):
        raise ValueError("must be a valid environment variable name")
    return value


def _unique_ports(ports: list[int]) -> list[int]:
    if len(ports) != len(set(ports)):
        raise ValueError("tunnel ports must be unique")
    return ports


type EnvironmentName = Annotated[str, AfterValidator(_environment_name)]
type TunnelPorts = Annotated[
    list[Annotated[int, Field(strict=True, ge=1, le=65535)]], AfterValidator(_unique_ports)
]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HostConfig(FrozenModel):
    """Placement settings for one SSH Host."""

    forward_environment: list[EnvironmentName] = Field(default_factory=list)
    platform: ImagePlatform | None = None
    container: ContainerSpec | None = None


class ProjectPlacement(FrozenModel):
    """Overrides applied after Project defaults and Project fields."""

    platform: ImagePlatform | None = None
    image: NonBlankString | None = None
    container: ContainerSpec | None = None


class ProjectDefaults(FrozenModel):
    image: NonBlankString
    tunnel_ports: TunnelPorts = Field(default_factory=list)
    container: ContainerSpec = Field(default_factory=ContainerSpec)


class ProjectConfig(FrozenModel):
    description: NonBlankString | None = None
    source: Source
    hosts: dict[HostId, ProjectPlacement] = Field(min_length=1)
    image: NonBlankString | None = None
    checkout_path: WorkspacePath | None = None
    open_path: WorkspacePath | None = None
    encrypted: bool = False
    tunnel_ports: TunnelPorts | None = None
    container: ContainerSpec | None = None

    def resolved_checkout_path(self) -> str:
        if self.checkout_path is not None:
            return self.checkout_path
        name = self.source.checkout_name
        return workspace_path(WORKSPACE_MOUNT if name is None else f"{WORKSPACE_MOUNT}/{name}")

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
            project.resolved_checkout_path()
            project.resolved_open_path()
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
            self.hosts[host].container,
            configured.container,
            placement.container,
        )

    def resolved_service_container(self, service: str, host: str) -> ContainerSpec:
        configured = self.services[service]
        return ContainerSpec().merged_with(
            self.hosts[host].container,
            configured.container,
            configured.hosts[host].container,
        )

    def project_image(self, project: str, host: str) -> str:
        configured = self.projects[project]
        placement = configured.hosts[host]
        return placement.image or configured.image or self.project_defaults.image

    def project_platform(self, project: str, host: str) -> ImagePlatform | None:
        return self.projects[project].hosts[host].platform or self.hosts[host].platform

    def project_tunnel_ports(self, project: str) -> list[int]:
        ports = self.projects[project].tunnel_ports
        return self.project_defaults.tunnel_ports if ports is None else ports

    def service_image(self, service: str, host: str) -> str:
        configured = self.services[service]
        return configured.hosts[host].image or configured.image

    def workspace_spec(self, project: str, host: str, workspace: str) -> WorkspaceSpec:
        configured = self.projects[project]
        return WorkspaceSpec(
            project=project,
            workspace=workspace,
            host=host,
            source=configured.source,
            platform=self.project_platform(project, host),
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
        for volume in container.volumes or []:
            volume.mount()
            if any(_paths_overlap(volume.target, reserved) for reserved in _RESERVED_MOUNTS):
                raise ValueError(
                    f"project volume targeting {volume.target!r} overlaps reserved mount target"
                )
        for secret in container.secrets or []:
            if secret.source == WORKSPACE_KEY_SECRET:
                raise ValueError(f"project secret {secret.source!r} overrides a reserved secret")
            target = secret.target or f"/run/secrets/{secret.source}"
            if any(_paths_overlap(target, reserved) for reserved in _RESERVED_MOUNTS):
                raise ValueError(
                    f"project secret {secret.source!r} overlaps a reserved mount target"
                )

    @classmethod
    def _validate_service_container(
        cls,
        service: str,
        host: str,
        container: ContainerSpec,
    ) -> None:
        cls._validate_network(f"service {service!r}", host, container)
        for volume in container.volumes or []:
            if volume.source != SERVICE_DATA_PLACEHOLDER:
                volume.mount()


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
        raw = yaml.safe_load(config_file)
    if not isinstance(raw, dict):
        raise ValueError(f"config {path.resolve()} must be a mapping")
    return Config.model_validate(raw)
