"""Single-file configuration schema and placement resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    model_validator,
)

from codespace.resources import HostId, Resource, ResourceId, ResourceNotFound
from codespace.runtime.container import (
    ContainerPorts,
    ContainerSpec,
    ContainerVolumes,
    ImagePlatform,
    NonBlankString,
    SecretSpec,
    UlimitSpec,
)
from codespace.services import ServiceSpec
from codespace.workspaces import (
    WORKSPACE_KEY_SECRET,
    WORKSPACE_MOUNT,
    EmptySource,
    GitProvider,
    Source,
    TokenString,
    WorkspacePath,
    WorkspaceSpec,
    workspace_path,
)

CONFIG_PATH = Path("/Users/x/.config/codespace/config.yaml")

type TcpPort = Annotated[StrictInt, Field(ge=1, le=65535)]
type TunnelPorts = list[TcpPort]


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ContainerLayer(FrozenModel):
    """One configuration override; null inherits and empty collections replace."""

    cap_add: list[NonBlankString] | None = None
    security_opt: list[NonBlankString] | None = None
    ipc: NonBlankString | None = None
    pids_limit: StrictInt | None = None
    ulimits: dict[NonBlankString, UlimitSpec] | None = None
    volumes: ContainerVolumes | None = None
    environment: dict[NonBlankString, str] | None = None
    secrets: list[SecretSpec] | None = None
    devices: list[NonBlankString] | None = None
    ports: ContainerPorts | None = None
    shm_size: NonBlankString | None = None


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
                for volume in (item.model_dump() for item in layer.volumes):
                    position = next(
                        (
                            index
                            for index, current in enumerate(volumes)
                            if current["source"] == volume["source"]
                            or current["target"] == volume["target"]
                        ),
                        None,
                    )
                    if position is not None:
                        volumes[position] = volume
                    else:
                        volumes.append(volume)
                merged["volumes"] = volumes
    return merged


class HostConfig(FrozenModel):
    """Placement settings for one SSH Host."""

    forward_environment: list[NonBlankString] = Field(default_factory=list)
    platform: ImagePlatform | None = None
    container: ContainerLayer | None = None


class ProjectDefaults(FrozenModel):
    image: NonBlankString
    encrypted: bool = False
    tunnel_ports: TunnelPorts = Field(default_factory=list)
    container: ContainerLayer = Field(default_factory=ContainerLayer)


class ProjectConfig(FrozenModel):
    description: NonBlankString | None = None
    source: Source
    hosts: list[HostId]
    image: NonBlankString | None = None
    checkout_path: WorkspacePath | None = None
    open_path: WorkspacePath | None = None
    encrypted: bool | None = None
    tunnel_ports: TunnelPorts | None = None
    container: ContainerLayer | None = None

    def resolved_checkout_path(self) -> str:
        if self.checkout_path is not None:
            return self.checkout_path
        name = None if isinstance(self.source, EmptySource) else self.source.checkout_name
        return workspace_path(WORKSPACE_MOUNT if name is None else f"{WORKSPACE_MOUNT}/{name}")

    def resolved_open_path(self) -> str:
        return self.open_path or self.resolved_checkout_path()


class ServiceConfig(FrozenModel):
    image: NonBlankString
    hosts: list[HostId]
    container: ContainerLayer = Field(default_factory=ContainerLayer)


class TokensConfig(FrozenModel):
    github: TokenString | None = Field(default=None, repr=False)
    gitlab: TokenString | None = Field(default=None, repr=False)


class Config(FrozenModel):
    """Complete immutable Codespace configuration."""

    hosts: dict[HostId, HostConfig]
    project_defaults: ProjectDefaults
    projects: dict[ResourceId, ProjectConfig] = Field(default_factory=dict)
    services: dict[ResourceId, ServiceConfig] = Field(default_factory=dict)
    tokens: TokensConfig = Field(default_factory=TokensConfig, repr=False)
    secrets: dict[NonBlankString, NonBlankString] = Field(default_factory=dict, repr=False)

    @model_validator(mode="after")
    def _validate_contracts(self) -> Config:
        for project_id, project in self.projects.items():
            project.resolved_checkout_path()
            for host in project.hosts:
                if host not in self.hosts:
                    raise ValueError(f"project {project_id!r} references unknown host {host!r}")
            if self.project_encrypted(project_id) and WORKSPACE_KEY_SECRET not in self.secrets:
                raise ValueError(
                    f"encrypted project {project_id!r} requires secret {WORKSPACE_KEY_SECRET!r}"
                )
        for service_id, service in self.services.items():
            for host in service.hosts:
                if host not in self.hosts:
                    raise ValueError(f"service {service_id!r} references unknown host {host!r}")
        return self

    def resolved_project_container(self, project: str, host: str) -> ContainerSpec:
        configured = self.projects[project]
        merged = _merge_container_layers(
            self.project_defaults.container,
            self.hosts[host].container,
            configured.container,
        )
        return ContainerSpec.model_validate(merged)

    def resolved_service_container(self, service: str, host: str) -> ContainerSpec:
        configured = self.services[service]
        merged = _merge_container_layers(
            self.hosts[host].container,
            configured.container,
        )
        return ContainerSpec.model_validate(merged)

    def project_image(self, project: str) -> str:
        configured = self.projects[project]
        return configured.image or self.project_defaults.image

    def project_tunnel_ports(self, project: str) -> list[int]:
        ports = self.projects[project].tunnel_ports
        return self.project_defaults.tunnel_ports if ports is None else ports

    def project_encrypted(self, project: str) -> bool:
        encrypted = self.projects[project].encrypted
        return self.project_defaults.encrypted if encrypted is None else encrypted

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
            f"tunnel port {published_port} is not published for service {service!r}"
        )

    def workspace_spec(self, project: str, host: str, workspace: str) -> WorkspaceSpec:
        configured = self.projects[project]
        return WorkspaceSpec(
            project=project,
            workspace=workspace,
            host=host,
            source=configured.source,
            platform=self.hosts[host].platform,
            image=self.project_image(project),
            container=self.resolved_project_container(project, host),
            checkout_path=configured.resolved_checkout_path(),
            open_path=configured.resolved_open_path(),
            encrypted=self.project_encrypted(project),
        )

    def service_spec(self, service: str, host: str) -> ServiceSpec:
        return ServiceSpec(
            service=service,
            host=host,
            image=self.services[service].image,
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


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Read and validate the one canonical YAML configuration file."""
    with path.open("rb") as config_file:
        raw = yaml.safe_load(config_file)
    if not isinstance(raw, dict):
        raise ValueError(f"config {path.resolve()} must be a mapping")
    return Config.model_validate(raw)
