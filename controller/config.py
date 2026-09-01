"""Codespace configuration schema, resolution and YAML loading."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self, cast

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from controller.models import (
    CONTROL_MOUNT,
    DEVSPACE_RUNLEVEL_ENV,
    LABEL_DEPLOYMENT,
    LABEL_DEPLOYMENT_ID,
    LABEL_GIT_URL,
    LABEL_IMAGE,
    LABEL_INSTANCE,
    LABEL_MANAGED,
    LABEL_PLATFORM,
    LABEL_PROVIDER,
    LABEL_REPO,
    LABEL_SSH_PORT,
    LABEL_TYPE,
    LABEL_WORKSPACE,
    PODMAN_SOCKET,
    RESOURCE_ID_RE,
    WORKSPACE_CLONE_PATH_ENV,
    WORKSPACE_CLONE_URL_ENV,
    WORKSPACE_MOUNT,
    WORKSPACE_OPEN_PATH_ENV,
    WORKSPACE_TYPE_ENV,
    Environment,
    GitProvider,
    GitUrl,
    HostId,
    ImagePlatform,
    NonBlankString,
    PlatformSelection,
    RepoPath,
    TokenString,
    environment_id,
    parse_port_mapping,
    platform_label,
    ssh_port,
    workspace_open_path,
)
from controller.models import (
    deployment_id as deployment_container_id,
)
from controller.runtime.compose import Secret, ServiceSpec, Volume
from controller.runtime.transport import HostEndpoint

CONFIG_PATH = Path.home() / "devspace" / "config.extend.yaml"

# Derived per container and forbidden in passthrough environment values.
_RESERVED_ENV_KEYS = frozenset(
    {
        "SSHD_PORT",
        "SSHD_BIND",
        DEVSPACE_RUNLEVEL_ENV,
        WORKSPACE_TYPE_ENV,
        WORKSPACE_CLONE_URL_ENV,
        WORKSPACE_CLONE_PATH_ENV,
        WORKSPACE_OPEN_PATH_ENV,
    }
)
_RESERVED_MOUNT_TARGETS = ("/workspace", "/upload", "/cache", CONTROL_MOUNT)
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


def _validate_port_mappings(value: list[str]) -> list[str]:
    """Reject malformed mappings and duplicate host bindings."""
    seen_local: set[int] = set()
    for spec in value:
        local, _remote = parse_port_mapping(spec)
        if local in seen_local:
            raise ValueError(f"duplicate published host port {local}")
        seen_local.add(local)
    return value


type PublishedPorts = Annotated[list[str], AfterValidator(_validate_port_mappings)]


class ContainerConfig(ServiceSpec):
    """Compose service subset with Codespace-specific validation."""

    @field_validator("environment")
    @classmethod
    def _reject_reserved(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is not None and (reserved := _RESERVED_ENV_KEYS & value.keys()):
            raise ValueError(
                f"container.environment must not set control-plane keys {sorted(reserved)}"
            )
        return value

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

    @model_validator(mode="after")
    def _reject_shm_size_with_host_ipc(self) -> Self:
        if self.ipc == "host" and self.shm_size is not None:
            raise ValueError("container.shm_size cannot be set when container.ipc is 'host'")
        return self

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
    deployments: list[NonBlankString] = Field(default_factory=list)
    container: ContainerConfig | None = None

    @field_validator("podman_socket")
    @classmethod
    def _validate_podman_socket(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("podman_socket must be an absolute path")
        return value

    @field_validator("deployments")
    @classmethod
    def _validate_deployments(cls, value: list[str]) -> list[str]:
        duplicates = sorted({name for name in value if value.count(name) > 1})
        if duplicates:
            raise ValueError(f"deployments must not repeat: {duplicates}")
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

    def endpoint(self) -> HostEndpoint:
        """Return the neutral Podman endpoint for this host."""
        return HostEndpoint(
            type=self.type,
            podman_socket=self.podman_socket,
            machine=self.machine,
        )


class TokensConfig(BaseModel):
    """Optional startup values for the process-local token store."""

    model_config = ConfigDict(extra="forbid")

    github: TokenString | None = Field(default=None, repr=False)
    gitlab: TokenString | None = Field(default=None, repr=False)


class WorkspaceHost(BaseModel):
    """One target host for a workspace with its per-host image platform."""

    model_config = ConfigDict(extra="forbid")

    name: HostId
    platform: ImagePlatform | None = None


class _BaseWorkspace(BaseModel):
    """Fields shared by every workspace type and the hosts it can run on.

    The concrete ``type`` decides which repository fields are required; that
    contract is expressed by the ``RepoWorkspace``/``GitWorkspace``/``BlankWorkspace``
    subclasses below and resolved through the ``WorkspaceConfig`` discriminated
    union, so consumers narrow on the class instead of re-checking ``type``.
    """

    model_config = ConfigDict(extra="forbid")

    host: list[WorkspaceHost]
    provider: GitProvider | None = None
    repo: RepoPath | None = None
    git_url: GitUrl | None = None
    description: NonBlankString | None = None
    image: NonBlankString | None = None
    open_path: NonBlankString | None = None
    clone_path: WorkspacePath | None = None
    published_ports: PublishedPorts | None = None
    encrypt_workspace: bool = False
    container: ContainerConfig | None = None

    @field_validator("host")
    @classmethod
    def _validate_host(cls, value: list[WorkspaceHost]) -> list[WorkspaceHost]:
        if not value:
            raise ValueError("host must list at least one target host")
        duplicates = sorted({e.name for e in value if [x.name for x in value].count(e.name) > 1})
        if duplicates:
            raise ValueError(f"host must not list a host more than once: {duplicates}")
        return value

    def host_platform(self, host: str) -> ImagePlatform | None:
        """Return the configured image platform for one of the workspace's hosts."""
        for entry in self.host:
            if entry.name == host:
                return entry.platform
        raise KeyError(f"workspace has no host {host!r}")

    @field_validator("open_path")
    @classmethod
    def _validate_open_path(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("open_path must be an absolute path")
        return value

    def resolved_clone_path(self) -> str:
        """Return the checkout directory, defaulting to the workspace-derived target."""
        if self.clone_path is not None:
            return str(self.clone_path)
        return workspace_open_path(self.repo, self.git_url)

    def resolved_open_path(self) -> str:
        """Return the editor open path, defaulting to the checkout directory."""
        return self.open_path or self.resolved_clone_path()


class RepoWorkspace(_BaseWorkspace):
    """Workspace cloned from a managed GitHub/GitLab repository via a deploy key."""

    type: Literal["repo"] = "repo"
    repo: RepoPath
    provider: GitProvider
    git_url: None = None


class GitWorkspace(_BaseWorkspace):
    """Workspace cloned directly from a raw git+ssh URL, with no managed credential."""

    type: Literal["git"]
    git_url: GitUrl
    repo: None = None
    provider: None = None


class BlankWorkspace(_BaseWorkspace):
    """Workspace with an empty checkout tree and no repository."""

    type: Literal["blank"]
    repo: None = None
    provider: None = None
    git_url: None = None
    clone_path: None = None


def _normalize_workspace(data: object) -> object:
    """Expand the ``repo`` shorthand and default ``type`` before union discrimination.

    Runs before the discriminated union picks a member, so it must set the
    ``type`` tag that selection relies on. ``repo: <provider>:<owner>/<name>``
    splits into ``provider``/``repo``; ``repo: git:<url>`` becomes a git workspace.
    """
    if not isinstance(data, dict):
        return data
    normalized = dict(data)
    repo = normalized.get("repo")
    if isinstance(repo, str) and ":" in repo:
        provider, _, rest = repo.partition(":")
        if provider == "git":
            if "git_url" in normalized:
                raise ValueError("set either combined 'repo' or separate 'git_url', not both")
            normalized.update(type="git", git_url=rest, repo=None)
            return normalized
        if "provider" in normalized:
            raise ValueError("set either combined 'repo' or separate 'provider', not both")
        normalized.update(provider=provider, repo=rest)
    normalized.setdefault("type", "repo")
    return normalized


type WorkspaceConfig = Annotated[
    Annotated[RepoWorkspace | GitWorkspace | BlankWorkspace, Field(discriminator="type")],
    BeforeValidator(_normalize_workspace),
]


class WorkspaceDefaults(BaseModel):
    """Development-container defaults shared by every workspace.

    These are the privileged, development-only defaults (image, host network,
    NET_RAW/SYS_ADMIN, relaxed seccomp, the krb5 mount) that only ever serve
    workspaces; deployments deliberately do not inherit them.
    """

    model_config = ConfigDict(extra="forbid")

    image: NonBlankString
    container: ContainerConfig = Field(default_factory=ContainerConfig)


class WorkspacesConfig(BaseModel):
    """The workspace catalog: shared development defaults plus each blueprint."""

    model_config = ConfigDict(extra="forbid")

    defaults: WorkspaceDefaults
    items: dict[str, WorkspaceConfig]


class DeploymentConfig(BaseModel):
    """A host-level deployment: a self-contained image with no repository checkout.

    Unlike a project, a deployment carries no workspace, SSH projection or git
    credential. It names an explicit ``image`` and a reusable ``container`` block;
    which hosts run it is declared the other way round, by ``hosts.<host>.deployments``.
    A ``${DEPLOYMENT_DATA}`` placeholder in a volume source resolves to the
    deployment's managed data directory below the host data root.
    """

    model_config = ConfigDict(extra="forbid")

    image: NonBlankString
    published_ports: PublishedPorts | None = None
    container: ContainerConfig | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentSpec:
    """Fully resolved inputs for one configured workspace instance."""

    workspace_id: str
    instance: str
    host: str
    platform: ImagePlatform | None
    workspace: WorkspaceConfig
    image: str
    container: ContainerConfig
    published_ports: tuple[tuple[int, int], ...]
    open_path: str
    clone_path: str

    @property
    def identity(self) -> str:
        return environment_id(self.host, self.workspace_id, self.instance)

    @property
    def ssh_port(self) -> int:
        return ssh_port(self.identity)

    @property
    def platform_label(self) -> PlatformSelection:
        return platform_label(self.platform)

    def to_environment(self, container_id: str, *, status: str | None = None) -> Environment:
        return Environment(
            id=self.identity,
            host=self.host,
            workspace=self.workspace_id,
            instance=self.instance,
            type=self.workspace.type,
            repo=self.workspace.repo,
            provider=self.workspace.provider,
            git_url=self.workspace.git_url,
            image=self.image,
            platform=self.platform_label,
            ssh_port=self.ssh_port,
            container_id=container_id,
            status=status,
        )

    def labels(self) -> dict[str, str]:
        labels = {
            LABEL_MANAGED: "true",
            LABEL_WORKSPACE: self.workspace_id,
            LABEL_INSTANCE: self.instance,
            LABEL_TYPE: self.workspace.type,
            LABEL_IMAGE: self.image,
            LABEL_PLATFORM: self.platform_label,
            LABEL_SSH_PORT: str(self.ssh_port),
        }
        if self.workspace.repo is not None and self.workspace.provider is not None:
            labels[LABEL_REPO] = self.workspace.repo
            labels[LABEL_PROVIDER] = self.workspace.provider
        if self.workspace.git_url is not None:
            labels[LABEL_GIT_URL] = self.workspace.git_url
        return labels


@dataclass(frozen=True, slots=True)
class DeploymentSpec:
    """Fully resolved inputs for one host-level deployment on one host."""

    deployment_id: str
    host: str
    image: str
    container: ContainerConfig
    published_ports: tuple[tuple[int, int], ...]

    @property
    def identity(self) -> str:
        return deployment_container_id(self.deployment_id)

    def labels(self) -> dict[str, str]:
        return {
            LABEL_DEPLOYMENT: "true",
            LABEL_DEPLOYMENT_ID: self.deployment_id,
            LABEL_IMAGE: self.image,
        }


class Config(BaseModel):
    """Complete immutable Codespace configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    hosts: dict[HostId, HostConfig]
    workspaces: WorkspacesConfig
    deployments: dict[str, DeploymentConfig] = Field(default_factory=dict)
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
    def _validate_workspaces(self) -> Self:
        if not self.workspaces.items:
            raise ValueError("workspaces.items must contain at least one workspace")
        for workspace_id, workspace in self.workspaces.items.items():
            if not RESOURCE_ID_RE.fullmatch(workspace_id):
                raise ValueError(
                    f"workspace {workspace_id!r} must match ^[a-z0-9][a-z0-9-]{{0,31}}$"
                )
            for entry in workspace.host:
                if entry.name not in self.hosts:
                    raise ValueError(
                        f"workspace {workspace_id!r} references unknown host {entry.name!r}"
                    )
                resolved = self.resolved_container(workspace_id, entry.name)
                if resolved.network_mode is None:
                    raise ValueError(
                        f"workspace {workspace_id!r} on host {entry.name!r} has no resolved "
                        "container.network_mode; set it on the workspaces.defaults, host, or "
                        "workspace container block"
                    )
                if workspace.published_ports and not resolved.is_bridge:
                    raise ValueError(
                        f"workspace {workspace_id!r} sets 'published_ports' but its resolved "
                        f"container.network_mode on host {entry.name!r} is not 'bridge'; "
                        "port publishing requires bridge mode"
                    )
                inherited = set(self.hosts[entry.name].environment)
                explicit = set(resolved.environment or {})
                collisions = sorted(inherited & explicit)
                if collisions:
                    raise ValueError(
                        f"workspace {workspace_id!r} on host {entry.name!r} configures inherited "
                        f"host environment variables {collisions} in container.environment"
                    )
                secret_env = set(_env_secret_targets(resolved.secrets))
                secret_collisions = sorted(inherited & secret_env)
                if secret_collisions:
                    raise ValueError(
                        f"workspace {workspace_id!r} on host {entry.name!r} configures inherited "
                        f"host environment variables {secret_collisions} as container.secrets "
                        "env target"
                    )
        return self

    @model_validator(mode="after")
    def _validate_deployments(self) -> Self:
        """Check deployment ids and that every host's placement resolves cleanly."""
        for deployment_id in self.deployments:
            if not RESOURCE_ID_RE.fullmatch(deployment_id):
                raise ValueError(
                    f"deployment {deployment_id!r} must match ^[a-z0-9][a-z0-9-]{{0,31}}$"
                )
        for host_id, host in self.hosts.items():
            for deployment_id in host.deployments:
                if deployment_id not in self.deployments:
                    raise ValueError(
                        f"host {host_id!r} references unknown deployment {deployment_id!r}"
                    )
                resolved = self.resolved_deployment_container(deployment_id, host_id)
                if resolved.network_mode is None:
                    raise ValueError(
                        f"deployment {deployment_id!r} on host {host_id!r} has no resolved "
                        "container.network_mode; set it on the host or deployment "
                        "container block"
                    )
        return self

    def deployment_hosts(self, deployment_id: str) -> list[str]:
        """Return the hosts that declared this deployment, in host declaration order."""
        return [
            host_id for host_id, host in self.hosts.items() if deployment_id in host.deployments
        ]

    def resolved_deployment_container(self, deployment_id: str, host: str) -> ContainerConfig:
        """Apply host and deployment container layers in order for one host.

        Unlike a workspace, a deployment does not inherit the development
        defaults in ``workspaces.defaults.container`` (privileged caps, relaxed
        seccomp, the krb5 mount): layering starts from an empty block, then
        ``host -> deployment``, so a deployment only carries what it declares.
        """
        deployment = self.deployments[deployment_id]
        return ContainerConfig().merged_with(
            self.hosts[host].container,
            deployment.container,
        )

    def deployment_spec(self, deployment_id: str, host: str) -> DeploymentSpec:
        """Resolve all configured inputs for one deployment on one host."""
        deployment = self.deployments[deployment_id]
        return DeploymentSpec(
            deployment_id=deployment_id,
            host=host,
            image=deployment.image,
            container=self.resolved_deployment_container(deployment_id, host),
            published_ports=tuple(
                parse_port_mapping(port) for port in deployment.published_ports or []
            ),
        )

    def workspace_image(self, workspace_id: str) -> str:
        """Resolve a workspace image against the required default image."""
        return self.workspaces.items[workspace_id].image or self.workspaces.defaults.image

    def workspace_open_path(self, workspace_id: str) -> str:
        """Resolve one workspace's editor open path, defaulting per type."""
        return self.workspaces.items[workspace_id].resolved_open_path()

    def workspace_clone_path(self, workspace_id: str) -> str:
        """Resolve one workspace's checkout directory, defaulting per type."""
        return self.workspaces.items[workspace_id].resolved_clone_path()

    def workspace_ports(self, workspace_id: str) -> list[tuple[int, int]]:
        """Resolve one workspace's published ``(local, remote)`` port mappings."""
        ports = self.workspaces.items[workspace_id].published_ports
        if not ports:
            return []
        return [parse_port_mapping(spec) for spec in ports]

    def resolved_container(self, workspace_id: str, host: str) -> ContainerConfig:
        """Apply defaults, host and workspace container layers in order for one host."""
        workspace = self.workspaces.items[workspace_id]
        return self.workspaces.defaults.container.merged_with(
            self.hosts[host].container,
            workspace.container,
        )

    def environment_spec(self, workspace_id: str, host: str, instance: str) -> EnvironmentSpec:
        """Resolve all configured inputs for one workspace instance on one host."""
        workspace = self.workspaces.items[workspace_id]
        return EnvironmentSpec(
            workspace_id=workspace_id,
            instance=instance,
            host=host,
            platform=workspace.host_platform(host),
            workspace=workspace,
            image=self.workspace_image(workspace_id),
            container=self.resolved_container(workspace_id, host),
            published_ports=tuple(self.workspace_ports(workspace_id)),
            open_path=self.workspace_open_path(workspace_id),
            clone_path=self.workspace_clone_path(workspace_id),
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


def _merge_layer(base: object, override: object) -> object:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[key] = _merge_layer(merged[key], value) if key in merged else value
        return merged
    return override


def _load_layers(path: Path, seen: frozenset[Path] = frozenset()) -> dict[str, object]:
    resolved = path.resolve()
    if resolved in seen:
        raise ValueError(f"config 'extends' chain forms a cycle at {resolved}")
    with resolved.open("rb") as config_file:
        raw = yaml.safe_load(config_file) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config {resolved} must be a mapping")
    extends = raw.pop("extends", None)
    if extends is None:
        return raw
    if not isinstance(extends, str) or not extends.strip():
        raise ValueError(f"config {resolved} 'extends' must be a non-empty path string")
    base = _load_layers(resolved.parent / extends, seen | {resolved})
    return cast("dict[str, object]", _merge_layer(base, raw))


def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load all YAML layers and validate the resulting configuration."""
    return Config.model_validate(_load_layers(path))
