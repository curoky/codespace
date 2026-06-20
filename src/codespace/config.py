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
    StrictInt,
    model_validator,
)

from codespace.runtime.container import (
    ComposeNonBlankString,
    ComposeString,
    ContainerPorts,
    ContainerSpec,
    ContainerVolumes,
    ImagePlatform,
    NonBlankString,
    SecretSpec,
    UlimitName,
    UlimitSpec,
    UniqueContainerOptions,
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
    WorkspaceContainerSpec,
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


class ContainerLayer(FrozenModel):
    """One configuration override; null inherits and empty collections replace."""

    cap_add: UniqueContainerOptions | None = None
    security_opt: UniqueContainerOptions | None = None
    network_mode: Literal["host", "bridge"] | None = None
    ipc: ComposeNonBlankString | None = None
    pids_limit: StrictInt | None = None
    ulimits: dict[UlimitName, UlimitSpec] | None = None
    volumes: ContainerVolumes | None = None
    environment: dict[NonBlankString, ComposeString] | None = None
    secrets: list[SecretSpec] | None = None
    devices: list[ComposeNonBlankString] | None = None
    ports: ContainerPorts | None = None
    shm_size: ComposeNonBlankString | None = None


def _merge_container_layers(*layers: ContainerLayer | None) -> dict[str, object]:
    merged: dict[str, object] = {}
    for layer in layers:
        if layer is not None:
            merged.update(layer.model_dump(exclude_none=True))
    return merged


class HostConfig(FrozenModel):
    """Placement settings for one SSH Host."""

    forward_environment: list[EnvironmentName] = Field(default_factory=list)
    platform: ImagePlatform | None = None
    container: ContainerLayer | None = None


class ProjectPlacement(FrozenModel):
    """Overrides applied after Project defaults and Project fields."""

    platform: ImagePlatform | None = None
    image: NonBlankString | None = None
    container: ContainerLayer | None = None


class ProjectDefaults(FrozenModel):
    image: NonBlankString
    tunnel_ports: TunnelPorts = Field(default_factory=list)
    container: ContainerLayer = Field(default_factory=ContainerLayer)


class ProjectConfig(FrozenModel):
    description: NonBlankString | None = None
    source: Source
    hosts: dict[HostId, ProjectPlacement] = Field(min_length=1)
    image: NonBlankString | None = None
    checkout_path: WorkspacePath | None = None
    open_path: WorkspacePath | None = None
    encrypted: bool = False
    tunnel_ports: TunnelPorts | None = None
    container: ContainerLayer | None = None

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
    container: ContainerLayer | None = None


class ServiceConfig(FrozenModel):
    image: NonBlankString
    hosts: dict[HostId, ServicePlacement] = Field(min_length=1)
    container: ContainerLayer = Field(default_factory=ContainerLayer)


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
                    self.resolved_service_container(service_id, host),
                )
        return self

    def project_hosts(self, project: str) -> list[str]:
        return list(self.projects[project].hosts)

    def service_hosts(self, service: str) -> list[str]:
        return list(self.services[service].hosts)

    def resolved_project_container(self, project: str, host: str) -> WorkspaceContainerSpec:
        configured = self.projects[project]
        placement = configured.hosts[host]
        merged = _merge_container_layers(
            self.project_defaults.container,
            self.hosts[host].container,
            configured.container,
            placement.container,
        )
        return WorkspaceContainerSpec.model_validate(merged)

    def resolved_service_container(self, service: str, host: str) -> ContainerSpec:
        configured = self.services[service]
        merged = _merge_container_layers(
            self.hosts[host].container,
            configured.container,
            configured.hosts[host].container,
        )
        return ContainerSpec.model_validate(merged)

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
    def _validate_project_container(
        project: str,
        container: WorkspaceContainerSpec,
    ) -> None:
        reserved_environment = _RESERVED_ENVIRONMENT.intersection(container.environment)
        if reserved_environment:
            names = ", ".join(sorted(reserved_environment))
            raise ValueError(f"project {project!r} overrides reserved environment: {names}")
        for volume in container.volumes:
            volume.mount()
            if any(_paths_overlap(volume.target, reserved) for reserved in _RESERVED_MOUNTS):
                raise ValueError(
                    f"project volume targeting {volume.target!r} overlaps reserved mount target"
                )
        for secret in container.secrets:
            if secret.source == WORKSPACE_KEY_SECRET:
                raise ValueError(f"project secret {secret.source!r} overrides a reserved secret")
            target = secret.target or f"/run/secrets/{secret.source}"
            if any(_paths_overlap(target, reserved) for reserved in _RESERVED_MOUNTS):
                raise ValueError(
                    f"project secret {secret.source!r} overlaps a reserved mount target"
                )

    @staticmethod
    def _validate_service_container(container: ContainerSpec) -> None:
        for volume in container.volumes:
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
