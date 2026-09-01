"""Codespace resource identity and API models."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

type GitProvider = Literal["github", "gitlab"]
type WorkspaceType = Literal["repo", "blank", "git"]
type OperationStatus = Literal["queued", "running", "failed"]
type HostState = Literal["online", "offline"]
type ImagePlatform = Literal["linux/amd64", "linux/arm64"]
type PlatformSelection = Literal["native", "linux/amd64", "linux/arm64"]

CONTAINER_USER = "x"
CONTAINER_UID = 5230
CONTAINER_GID = 5230
WORKSPACE_MOUNT = "/workspace"
# Each workspace instance also gets a persistent upload inbox, build cache and
# private control socket directory. All mounts are siblings below one instance root.
UPLOAD_MOUNT = "/upload"
CACHE_MOUNT = "/cache"
CONTROL_MOUNT = "/run/codespace-control"
# The host workspace is bind-mounted to the gocryptfs cipher directory; the
# image mounts the decrypted plaintext at WORKSPACE_MOUNT at boot, so only
# ciphertext ever reaches host disk while every /workspace consumer is unchanged.
WORKSPACE_CIPHER_MOUNT = "/workspace.enc"
# The gocryptfs password is a fixed secret distributed exactly like the
# sidecar's atuin_db_uri: declare it once in the top-level `secrets` block and
# register it out of band with sync_secrets (the sole distribution path). The
# control plane only injects it as WORKSPACE_CRYPT_KEY for workspaces that opt in
# via `encrypt_workspace`; a missing secret then fails container creation fast.
WORKSPACE_CRYPT_SECRET = "workspace_crypt_key"  # noqa: S105 - secret name, not a value
WORKSPACE_CRYPT_SECRET_ENV = "WORKSPACE_CRYPT_KEY"  # noqa: S105 - env var name, not a value
WORKSPACE_TYPE_ENV = "CODESPACE_WORKSPACE_TYPE"
WORKSPACE_CLONE_URL_ENV = "CODESPACE_CLONE_URL"
WORKSPACE_CLONE_PATH_ENV = "CODESPACE_CLONE_PATH"
WORKSPACE_OPEN_PATH_ENV = "CODESPACE_OPEN_PATH"
HOST_DATA_DIR_NAME = "codespace"
WORKSPACES_DATA_DIR_NAME = "workspaces"
DEPLOYMENTS_DATA_DIR_NAME = "deployments"
# A ``${DEPLOYMENT_DATA}`` prefix in a deployment volume source is replaced with
# that deployment's resolved data directory just before container creation.
DEPLOYMENT_DATA_PLACEHOLDER = "${DEPLOYMENT_DATA}"
PODMAN_SOCKET = "/run/podman/podman.sock"
SSH_PORT_START = 20_000
SSH_PORT_COUNT = 10_000

RESOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}$")
REPO_RE = re.compile(r"^[\w.-]+(?:/[\w.-]+)+$")
# SCP-style ``git@host:owner/name.git`` or ``ssh://git@host[:port]/owner/name.git``.
GIT_URL_RE = re.compile(
    r"^(?:ssh://)?[\w.-]+@[a-z0-9][a-z0-9.-]*(?::\d+)?[:/][\w./~-]+?(?:\.git)?/?$"
)

PORT_MIN = 1
PORT_MAX = 65_535


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
    port = int(token)
    if not PORT_MIN <= port <= PORT_MAX:
        raise ValueError(f"port must be between {PORT_MIN} and {PORT_MAX}, got {port}")
    return port


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
type GitUrl = Annotated[str, Field(pattern=GIT_URL_RE.pattern)]
type NonBlankString = Annotated[str, AfterValidator(_not_blank)]
type TokenString = Annotated[str, AfterValidator(_not_blank_token)]

LABEL_MANAGED = "codespace.managed"
LABEL_WORKSPACE = "codespace.workspace"
LABEL_INSTANCE = "codespace.instance"
LABEL_TYPE = "codespace.type"
LABEL_REPO = "codespace.repo"
LABEL_PROVIDER = "codespace.provider"
LABEL_GIT_URL = "codespace.git-url"
LABEL_IMAGE = "codespace.image"
LABEL_PLATFORM = "codespace.platform"
LABEL_SSH_PORT = "codespace.ssh-port"

# Deployments carry their own label family and are deliberately never tagged
# ``codespace.managed`` so environment inventory (which filters on that label)
# and deployment inventory stay strictly disjoint.
LABEL_DEPLOYMENT = "codespace.deployment"
LABEL_DEPLOYMENT_ID = "codespace.deployment-id"

# Shared by label generation and inventory validation.
MANDATORY_LABELS = (
    LABEL_WORKSPACE,
    LABEL_INSTANCE,
    LABEL_TYPE,
    LABEL_IMAGE,
    LABEL_PLATFORM,
    LABEL_SSH_PORT,
)

# Shared by deployment label generation and deployment inventory validation.
MANDATORY_DEPLOYMENT_LABELS = (
    LABEL_DEPLOYMENT_ID,
    LABEL_IMAGE,
)


@dataclass(frozen=True, slots=True)
class InstancePaths:
    """Absolute paths for one environment below a host data root."""

    root: str
    workspaces_root: str
    workspace: str
    upload: str
    cache: str
    control: str


@dataclass(frozen=True, slots=True)
class HostDataPaths:
    """Canonical data layout below one host's ``~/codespace`` directory."""

    root: str

    @property
    def workspaces(self) -> str:
        return f"{self.root}/{WORKSPACES_DATA_DIR_NAME}"

    @property
    def deployments(self) -> str:
        return f"{self.root}/{DEPLOYMENTS_DATA_DIR_NAME}"

    def instance(self, workspace: str, instance: str) -> InstancePaths:
        root = f"{self.workspaces}/{workspace}/{instance}"
        return InstancePaths(
            root=root,
            workspaces_root=self.workspaces,
            workspace=f"{root}{WORKSPACE_MOUNT}",
            upload=f"{root}{UPLOAD_MOUNT}",
            cache=f"{root}{CACHE_MOUNT}",
            control=f"{root}/control",
        )

    def deployment(self, deployment: str) -> str:
        return f"{self.deployments}/{deployment}"


def environment_id(host: str, workspace: str, instance: str) -> str:
    return f"codespace-{host}-{workspace}-{instance}"


def deployment_id(deployment: str) -> str:
    """Return the deterministic container name for a host-level deployment.

    A deployment is a host singleton, so unlike an environment its identity
    carries no host or instance component: one name per deployment id per host.
    """
    return f"codespace-{deployment}"


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


def workspace_open_path(repo: str | None, git_url: str | None = None) -> str:
    if repo is not None:
        return f"{WORKSPACE_MOUNT}/{repo.rsplit('/', 1)[-1].removesuffix('.git')}"
    if git_url is not None:
        trimmed = git_url.rstrip("/").removesuffix(".git")
        return f"{WORKSPACE_MOUNT}/{re.split(r'[/:]', trimmed)[-1]}"
    return WORKSPACE_MOUNT


def trae_url(alias: str, open_path: str, *, scheme: str = "trae") -> str:
    """Build a Trae Remote-SSH deep link for an environment."""
    return (
        f"{scheme}://vscode-remote/ssh-remote+{quote(alias, safe='')}"
        f"{quote(open_path, safe='/')}?windowId=_blank&fullscreen=true"
    )


class CreateInstanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: HostId
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


class DeleteDeploymentResult(BaseModel):
    """Outcome of cleaning one deployment's container and optional managed data."""

    removed: bool
    data_removed: bool = False


class ContainerLogsResult(BaseModel):
    """Recent combined stdout and stderr for one managed container."""

    logs: str


class Environment(BaseModel):
    id: str
    host: str
    workspace: str
    instance: str
    type: WorkspaceType
    repo: str | None = None
    provider: GitProvider | None = None
    git_url: str | None = None
    image: str
    platform: PlatformSelection
    ssh_port: int
    container_id: str
    status: str | None = None


class Deployment(BaseModel):
    """An actual deployment container read back from one host's inventory."""

    id: str
    deployment: str
    host: str
    image: str
    container_id: str
    status: str | None = None


class DashboardEnvironment(BaseModel):
    id: str
    host: str
    workspace: str
    instance: str
    type: WorkspaceType
    repo: str | None = None
    provider: GitProvider | None = None
    git_url: str | None = None
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


class WorkspaceSummaryHost(BaseModel):
    name: str
    platform: ImagePlatform | None = None


class WorkspaceSummary(BaseModel):
    id: str
    hosts: list[WorkspaceSummaryHost]
    type: WorkspaceType
    repo: str | None = None
    provider: GitProvider | None = None
    git_url: str | None = None
    image: str
    description: str | None = None
    open_path: str


class Operation(BaseModel):
    id: str
    host: str
    workspace: str
    instance: str
    status: OperationStatus
    stage: str
    error: str | None = None


class DeploymentOperation(BaseModel):
    """The current async lifecycle operation for one deployment on one host."""

    id: str
    host: str
    deployment: str
    status: OperationStatus
    stage: str
    error: str | None = None


type DeploymentState = Literal["running", "stopped", "missing"]


class DeploymentHostStatus(BaseModel):
    """One deployment's actual state on one host it was declared on."""

    host: str
    state: DeploymentState
    status: str | None = None
    container_id: str | None = None
    error: str | None = None
    operation: DeploymentOperation | None = None


class DeploymentSummary(BaseModel):
    """A deployment catalog entry projected with its per-host state."""

    id: str
    image: str
    hosts: list[DeploymentHostStatus]


class DashboardResponse(BaseModel):
    hosts: list[HostStatus]
    workspaces: list[WorkspaceSummary]
    environments: list[DashboardEnvironment]
    deployments: list[DeploymentSummary]
    operations: list[Operation]
    tokens: dict[GitProvider, bool]
