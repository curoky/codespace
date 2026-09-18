"""Single-file configuration schema and placement resolution."""

from __future__ import annotations

import re
from ipaddress import ip_address
from pathlib import Path, PurePosixPath
from typing import Annotated, cast

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    model_validator,
)

from codespace.resources import HostId, Resource, ResourceId, ResourceNotFound
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
from codespace.services import ServiceSpec
from codespace.workspaces import (
    CHECKOUT_PATH_ENV,
    CLONE_URL_ENV,
    CONTAINER_HOME,
    CONTAINER_STATE_ROOT,
    CONTROL_MOUNT,
    ENCRYPTED_ENV,
    ENCRYPTED_PATH_ENV,
    GIT_ARGS_ENV,
    OPEN_PATH_ENV,
    SOURCE_TYPE_ENV,
    UPLOAD_MOUNT,
    WORKSPACE_KEY_MOUNT,
    WORKSPACE_KEY_SECRET,
    WORKSPACE_MOUNT,
    EmptySource,
    GitProvider,
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
    GIT_ARGS_ENV,
    CHECKOUT_PATH_ENV,
    OPEN_PATH_ENV,
    ENCRYPTED_ENV,
}
_RESERVED_MOUNTS = (
    CONTAINER_STATE_ROOT,
    WORKSPACE_MOUNT,
    UPLOAD_MOUNT,
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


def _bridge_gateway(value: str) -> str:
    address = ip_address(value)
    if address.is_loopback or address.is_unspecified:
        raise ValueError("must be a Podman bridge gateway address")
    return str(address)


type EnvironmentName = Annotated[str, AfterValidator(_environment_name)]
type TunnelPorts = Annotated[
    list[Annotated[int, Field(strict=True, ge=1, le=65535)]], AfterValidator(_unique_ports)
]
type BridgeGateway = Annotated[str, AfterValidator(_bridge_gateway)]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContainerLayer(FrozenModel):
    """One configuration override; null inherits and empty collections replace."""

    cap_add: UniqueContainerOptions | None = None
    security_opt: UniqueContainerOptions | None = None
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
            merged.update(
                layer.model_dump(
                    exclude_none=True,
                    exclude={"environment", "volumes"},
                )
            )
            if layer.environment is not None:
                environment = dict(cast("dict[str, str]", merged.get("environment", {})))
                environment.update(layer.environment)
                merged["environment"] = environment
            if layer.volumes is not None:
                if not layer.volumes:
                    merged["volumes"] = []
                    continue
                volumes = list(cast("list[dict[str, object]]", merged.get("volumes", [])))
                positions = {volume["target"]: index for index, volume in enumerate(volumes)}
                for volume in (item.model_dump() for item in layer.volumes):
                    target = volume["target"]
                    if target in positions:
                        volumes[positions[target]] = volume
                    else:
                        positions[target] = len(volumes)
                        volumes.append(volume)
                merged["volumes"] = volumes
    return merged


class HostConfig(FrozenModel):
    """Placement settings for one SSH Host."""

    bridge_gateway: BridgeGateway
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
        name = None if isinstance(self.source, EmptySource) else self.source.checkout_name
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
        for host in self.hosts:
            if host.startswith("space-"):
                raise ValueError(f"host {host!r} uses the reserved Workspace SSH prefix 'space-'")
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
                    service_id,
                    self.hosts[host].bridge_gateway,
                    self.resolved_service_container(service_id, host),
                )
        return self

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

    def service_tunnel_ports(self, service: str, host: str) -> list[int]:
        return [
            port.published
            for port in self.resolved_service_container(service, host).ports
            if port.protocol == "tcp"
        ]

    def service_tunnel_host(self, service: str, host: str, published_port: int) -> str:
        for port in self.resolved_service_container(service, host).ports:
            if port.protocol == "tcp" and port.published == published_port:
                return port.host_ip
        raise ResourceNotFound(
            f"tunnel port {published_port} is not configured for service {service!r}"
        )

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

    def resource_spec(self, resource: Resource) -> WorkspaceSpec | ServiceSpec:
        """Validate desired placement for every resource operation."""
        kind = "project" if resource.project is not None else "service"
        name = resource.project if resource.project is not None else resource.name
        configured = (
            self.projects.get(name) if resource.project is not None else self.services.get(name)
        )
        if configured is None:
            raise ResourceNotFound(f"unknown {kind}: {name}")
        if resource.host not in configured.hosts:
            raise ResourceNotFound(
                f"host {resource.host!r} is not configured for {kind} {name!r}; "
                f"allowed: {sorted(configured.hosts)}"
            )
        if resource.project is not None:
            return self.workspace_spec(resource.project, resource.host, resource.name)
        return self.service_spec(resource.name, resource.host)

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
        encrypted_workspace_target = container.environment.get(ENCRYPTED_PATH_ENV)
        if encrypted_workspace_target is None:
            raise ValueError(f"project {project!r} requires environment {ENCRYPTED_PATH_ENV!r}")
        encrypted_path = PurePosixPath(encrypted_workspace_target)
        if not encrypted_path.is_absolute() or ".." in encrypted_path.parts:
            raise ValueError(f"{ENCRYPTED_PATH_ENV} must be an absolute normalized path")
        managed_targets = {
            volume.target for volume in container.volumes if volume.uses_resource_data
        }
        managed_targets.add(encrypted_workspace_target)
        for volume in container.volumes:
            if not volume.uses_resource_data:
                volume.mount()
            if not volume.uses_resource_data and any(
                _paths_overlap(volume.target, reserved)
                for reserved in (*_RESERVED_MOUNTS, *managed_targets)
            ):
                raise ValueError(
                    f"project volume targeting {volume.target!r} overlaps reserved mount target"
                )
        for encrypted in (False, True):
            targets = [
                encrypted_workspace_target
                if encrypted and volume.target == WORKSPACE_MOUNT
                else volume.target
                for volume in container.volumes
            ]
            required = {
                encrypted_workspace_target if encrypted else WORKSPACE_MOUNT,
                UPLOAD_MOUNT,
                CONTROL_MOUNT,
            }
            if missing := required.difference(targets):
                raise ValueError(f"Workspace volumes missing required targets: {sorted(missing)}")
            for index, target in enumerate(targets):
                if any(_paths_overlap(target, other) for other in targets[:index]):
                    raise ValueError(f"Workspace volume {target!r} overlaps another volume")
                configured = container.volumes[index]
                if configured.uses_resource_data and (
                    any(
                        _paths_overlap(target, reserved)
                        for reserved in (CONTAINER_STATE_ROOT, WORKSPACE_KEY_MOUNT)
                    )
                    or PurePosixPath(CONTAINER_HOME).is_relative_to(target)
                ):
                    raise ValueError(f"Workspace volume {target!r} overlaps image-owned state")
                if (
                    configured.uses_resource_data
                    and encrypted
                    and _paths_overlap(target, WORKSPACE_MOUNT)
                ):
                    raise ValueError("encrypted Workspace must leave /workspace for gocryptfs")
        for secret in container.secrets:
            if secret.source == WORKSPACE_KEY_SECRET:
                raise ValueError(f"project secret {secret.source!r} overrides a reserved secret")
            target = secret.target or f"/run/secrets/{secret.source}"
            if any(
                _paths_overlap(target, reserved)
                for reserved in (*_RESERVED_MOUNTS, *managed_targets)
            ):
                raise ValueError(
                    f"project secret {secret.source!r} overlaps a reserved mount target"
                )

    @staticmethod
    def _validate_service_container(
        service: str,
        bridge_gateway: str,
        container: ContainerSpec,
    ) -> None:
        published_tcp: set[int] = set()
        for port in container.ports:
            if port.host_ip != bridge_gateway:
                raise ValueError(
                    f"service {service!r} ports must publish to Host bridge gateway "
                    f"{bridge_gateway}"
                )
            if port.protocol == "tcp" and port.published in published_tcp:
                raise ValueError("service TCP published ports must be unique")
            if port.protocol == "tcp":
                published_tcp.add(port.published)
        for volume in container.volumes:
            volume.resolve_data_path("/managed").mount()


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
