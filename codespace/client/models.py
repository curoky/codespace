"""Codespace resource identity and API models."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal
from urllib.parse import quote

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from codespace.client.config import ContainerConfig, ProjectConfig

type GitProvider = Literal["github", "gitlab"]
type ProjectType = Literal["repo", "blank"]
type OperationStatus = Literal["queued", "running", "failed"]
type HostState = Literal["online", "offline"]
type ImagePlatform = Literal["linux/amd64", "linux/arm64"]
type PlatformSelection = Literal["native", "linux/amd64", "linux/arm64"]

CONTAINER_USER = "x"
WORKSPACE_MOUNT = "/workspace"
# A bind-mount source requires the host's resolved absolute home path.
WORKSPACE_DIR_NAME = "codespace"
PODMAN_SOCKET = "/run/podman/podman.sock"
SSH_PORT_START = 20_000
SSH_PORT_COUNT = 10_000

RESOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}$")
REPO_RE = re.compile(r"^[\w.-]+(?:/[\w.-]+)+$")

PORT_MIN = 1
PORT_MAX = 65_535


def _valid_port(value: int) -> int:
    if not PORT_MIN <= value <= PORT_MAX:
        raise ValueError(f"port must be between {PORT_MIN} and {PORT_MAX}, got {value}")
    return value


def parse_port_mapping(value: str) -> tuple[int, int]:
    """Parse ``remote`` or ``local:remote`` into a validated port pair."""
    parts = value.split(":")
    if len(parts) == 1:
        remote = _parse_port_int(parts[0], value)
        return remote, remote
    if len(parts) == 2:
        local = _parse_port_int(parts[0], value)
        remote = _parse_port_int(parts[1], value)
        return local, remote
    raise ValueError(f"invalid port mapping {value!r}: expected 'remote' or 'local:remote'")


def _parse_port_int(token: str, original: str) -> int:
    if not token.isdigit():
        raise ValueError(f"invalid port mapping {original!r}: {token!r} is not a port number")
    return _valid_port(int(token))


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


def _not_blank_token(value: str) -> str:
    if not value.strip():
        raise ValueError("token must not be blank")
    return value


type ResourceId = Annotated[str, Field(pattern=RESOURCE_ID_RE.pattern)]
type HostId = Annotated[str, Field(pattern=HOST_RE.pattern)]
type RepoPath = Annotated[str, Field(pattern=REPO_RE.pattern)]
type NonBlankString = Annotated[str, AfterValidator(_not_blank)]
type TokenString = Annotated[str, AfterValidator(_not_blank_token)]

LABEL_MANAGED = "codespace.managed"
LABEL_PROJECT = "codespace.project"
LABEL_INSTANCE = "codespace.instance"
LABEL_TYPE = "codespace.type"
LABEL_REPO = "codespace.repo"
LABEL_PROVIDER = "codespace.provider"
LABEL_IMAGE = "codespace.image"
LABEL_PLATFORM = "codespace.platform"
LABEL_SSH_PORT = "codespace.ssh-port"

# Shared by label generation and inventory validation.
MANDATORY_LABELS = (
    LABEL_PROJECT,
    LABEL_INSTANCE,
    LABEL_TYPE,
    LABEL_IMAGE,
    LABEL_PLATFORM,
    LABEL_SSH_PORT,
)


@dataclass(frozen=True, slots=True)
class EnvironmentSpec:
    """Fully resolved inputs for one configured project instance."""

    project_id: str
    instance: str
    project: ProjectConfig
    image: str
    container: ContainerConfig
    published_ports: tuple[tuple[int, int], ...]
    open_path: str

    @property
    def identity(self) -> str:
        return environment_id(self.project.host, self.project_id, self.instance)

    @property
    def ssh_port(self) -> int:
        return ssh_port(self.identity)

    @property
    def platform_label(self) -> PlatformSelection:
        return platform_label(self.project.platform)

    def workspace_path(self, workspace_root: str) -> str:
        return f"{workspace_root}/{self.project_id}/{self.instance}"

    def to_environment(self, container_id: str, *, status: str | None = None) -> Environment:
        return Environment(
            id=self.identity,
            host=self.project.host,
            project=self.project_id,
            instance=self.instance,
            type=self.project.type,
            repo=self.project.repo,
            provider=self.project.provider,
            image=self.image,
            platform=self.platform_label,
            ssh_port=self.ssh_port,
            container_id=container_id,
            status=status,
        )


def environment_labels(spec: EnvironmentSpec) -> dict[str, str]:
    """Build the canonical label set for a managed container."""
    labels = {
        LABEL_MANAGED: "true",
        LABEL_PROJECT: spec.project_id,
        LABEL_INSTANCE: spec.instance,
        LABEL_TYPE: spec.project.type,
        LABEL_IMAGE: spec.image,
        LABEL_PLATFORM: spec.platform_label,
        LABEL_SSH_PORT: str(spec.ssh_port),
    }
    if spec.project.repo is not None and spec.project.provider is not None:
        labels[LABEL_REPO] = spec.project.repo
        labels[LABEL_PROVIDER] = spec.project.provider
    return labels


def environment_id(host: str, project: str, instance: str) -> str:
    return f"codespace-{host}-{project}-{instance}"


def ssh_port(identity: str) -> int:
    digest_prefix = hashlib.sha256(identity.encode()).hexdigest()[:4]
    return SSH_PORT_START + int(digest_prefix, 16) % SSH_PORT_COUNT


def platform_label(platform: ImagePlatform | None) -> PlatformSelection:
    """Map an omitted platform to the inventory label ``native``."""
    return platform if platform is not None else "native"


def git_host(provider: GitProvider) -> str:
    match provider:
        case "github":
            return "github.com"
        case "gitlab":
            return "gitlab.com"


def repo_target(repo: str) -> str:
    name = repo.rsplit("/", 1)[-1].removesuffix(".git")
    return f"{WORKSPACE_MOUNT}/{name}"


def workspace_open_path(repo: str | None) -> str:
    return repo_target(repo) if repo is not None else WORKSPACE_MOUNT


def trae_url(alias: str, open_path: str, *, scheme: str = "trae") -> str:
    """Build a Trae Remote-SSH deep link for an environment."""
    return (
        f"{scheme}://vscode-remote/ssh-remote+{quote(alias, safe='')}"
        f"{quote(open_path, safe='/')}?windowId=_blank&fullscreen=true"
    )


class CreateInstanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance: ResourceId


class UpdateTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: TokenString = Field(repr=False)


class RepoGitState(BaseModel):
    """Pre-delete safety check for a repo checkout inside a container."""

    unpushed: bool = False
    uncommitted: bool = False
    detail: list[str] = Field(default_factory=list)

    @property
    def blocks_delete(self) -> bool:
        return self.unpushed or self.uncommitted


class DeleteInstanceResult(BaseModel):
    deleted: bool
    workspace_removed: bool = False
    state: RepoGitState = Field(default_factory=RepoGitState)


class Environment(BaseModel):
    id: str
    host: str
    project: str
    instance: str
    type: ProjectType
    repo: str | None = None
    provider: GitProvider | None = None
    image: str
    platform: PlatformSelection
    ssh_port: int
    container_id: str
    status: str | None = None


class DashboardEnvironment(BaseModel):
    id: str
    host: str
    project: str
    instance: str
    type: ProjectType
    repo: str | None = None
    provider: GitProvider | None = None
    image: str
    platform: PlatformSelection
    ssh_port: int
    status: str | None = None
    alias: str
    ssh_command: str
    trae_url: str
    trae_cn_url: str

    @classmethod
    def from_environment(cls, environment: Environment, open_path: str) -> DashboardEnvironment:
        return cls(
            **environment.model_dump(exclude={"container_id"}),
            alias=environment.id,
            ssh_command=f"ssh {environment.id}",
            trae_url=trae_url(environment.id, open_path),
            trae_cn_url=trae_url(environment.id, open_path, scheme="trae-cn"),
        )


class HostStatus(BaseModel):
    id: str
    status: HostState
    environment_count: int = 0
    error: str | None = None
    inventory_errors: list[str] = Field(default_factory=list)


class ProjectSummary(BaseModel):
    id: str
    host: str
    type: ProjectType
    repo: str | None = None
    provider: GitProvider | None = None
    image: str
    platform: ImagePlatform | None = None
    description: str | None = None
    open_path: str


class Operation(BaseModel):
    id: str
    host: str
    project: str
    instance: str
    status: OperationStatus
    stage: str
    error: str | None = None


class DashboardResponse(BaseModel):
    hosts: list[HostStatus]
    projects: list[ProjectSummary]
    environments: list[DashboardEnvironment]
    operations: list[Operation]
    tokens: dict[GitProvider, bool]
