"""Codespace resource identity and API models."""

from __future__ import annotations

import hashlib
import re
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

type GitProvider = Literal["github", "gitlab"]
type ProjectType = Literal["repo", "blank"]
type OperationStatus = Literal["queued", "running", "failed"]
type HostState = Literal["online", "offline"]
type ImagePlatform = Literal["linux/amd64", "linux/arm64"]
type PlatformSelection = Literal["native", "linux/amd64", "linux/arm64"]

CONTAINER_USER = "x"
CONTAINER_UID = 5230
WORKSPACE_MOUNT = "/workspace"
# Host workspace root lives under the SSH login user's home so each host can use
# its own account. The absolute path is resolved per host at runtime because a
# Podman bind-mount source cannot contain '~'.
WORKSPACE_DIR_NAME = "codespace"
PODMAN_SOCKET = "/run/podman/podman.sock"
SSH_PORT_START = 20_000
SSH_PORT_COUNT = 10_000
# CDI device string injected when a host enables GPU access; equivalent to
# ``--device nvidia.com/gpu=all`` (CLAUDE.md 配置 gpu).
CDI_ALL_GPUS = "nvidia.com/gpu=all"

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
    """Parse one ``local:remote`` or single-port publish spec into ``(local, remote)``.

    A bare ``"8080"`` maps host 8080 to container 8080; ``"3000:5000"`` maps host
    3000 to container 5000. Both endpoints must be valid TCP ports. Malformed
    input raises rather than being silently ignored.
    """
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

# Labels every managed container carries, excluding the LABEL_MANAGED marker
# which is validated on its own. This tuple is the single source of truth shared
# by the write side (``environment_labels``) and the read side
# (``runtime._REQUIRED_LABELS``); the symmetry is asserted in the tests so that
# adding or removing a label cannot silently desynchronise the two paths.
MANDATORY_LABELS = (
    LABEL_PROJECT,
    LABEL_INSTANCE,
    LABEL_TYPE,
    LABEL_IMAGE,
    LABEL_PLATFORM,
    LABEL_SSH_PORT,
)
# Extra labels only repo projects carry; blank projects must omit them.
REPO_LABELS = (LABEL_REPO, LABEL_PROVIDER)


def environment_labels(
    *,
    project: str,
    instance: str,
    project_type: ProjectType,
    repo: str | None,
    provider: GitProvider | None,
    image: str,
    platform: PlatformSelection,
    ssh_port: int,
) -> dict[str, str]:
    """Build the canonical label set written onto a managed container.

    Single source of truth for the container label contract. ``read_environment``
    validates the same keys, so both sides stay symmetric (CLAUDE.md 资源标识).
    """
    labels = {
        LABEL_MANAGED: "true",
        LABEL_PROJECT: project,
        LABEL_INSTANCE: instance,
        LABEL_TYPE: project_type,
        LABEL_IMAGE: image,
        LABEL_PLATFORM: platform,
        LABEL_SSH_PORT: str(ssh_port),
    }
    if repo is not None and provider is not None:
        labels[LABEL_REPO] = repo
        labels[LABEL_PROVIDER] = provider
    return labels


def environment_id(host: str, project: str, instance: str) -> str:
    """Return the deterministic identity shared by all environment resources."""
    return f"codespace-{host}-{project}-{instance}"


def workspace_path(workspace_root: str, project: str, instance: str) -> str:
    """Return one environment's workspace path under a resolved host root."""
    return f"{workspace_root}/{project}/{instance}"


def ssh_port(identity: str) -> int:
    """Map an environment identity to its deterministic reserved SSH port."""
    digest_prefix = hashlib.sha256(identity.encode()).hexdigest()[:4]
    return SSH_PORT_START + int(digest_prefix, 16) % SSH_PORT_COUNT


def platform_label(platform: ImagePlatform | None) -> PlatformSelection:
    """Map an optional image platform to its label value.

    A project without an explicit ``platform`` runs on the host's native
    platform, recorded as the ``native`` label. Centralising the ``None`` ->
    ``"native"`` mapping keeps the write side (container labels) and the derived
    environment state from drifting to separate literals.
    """
    return platform if platform is not None else "native"


def git_host(provider: GitProvider) -> str:
    """Return the official SSH host for a supported provider."""
    match provider:
        case "github":
            return "github.com"
        case "gitlab":
            return "gitlab.com"


def repo_target(repo: str) -> str:
    """Return the checkout path inside the development container."""
    name = repo.rsplit("/", 1)[-1].removesuffix(".git")
    return f"{WORKSPACE_MOUNT}/{name}"


def workspace_open_path(repo: str | None) -> str:
    """Return the default editor open path for a project.

    A repo project opens its checkout directory; a blank project has no
    checkout so the editor opens the mounted workspace root directly.
    """
    return repo_target(repo) if repo is not None else WORKSPACE_MOUNT


def trae_url(alias: str, open_path: str, *, scheme: str = "trae") -> str:
    """Build a Trae Remote-SSH deep link for an environment."""
    return (
        f"{scheme}://vscode-remote/ssh-remote+{quote(alias, safe='')}"
        f"{quote(open_path, safe='/')}?windowId=_blank&fullscreen=true"
    )


class CreateInstanceRequest(BaseModel):
    """Request body for creating one configured project instance."""

    model_config = ConfigDict(extra="forbid")

    instance: ResourceId


class UpdateTokenRequest(BaseModel):
    """Request body for storing a provider token in process memory."""

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
    """Result of an inspect (``force=False``) or delete (``force=True``) call."""

    deleted: bool
    workspace_removed: bool = False
    state: RepoGitState = Field(default_factory=RepoGitState)


class Environment(BaseModel):
    """A managed development environment discovered from Podman."""

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
    """Browser-facing environment projection."""

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
    """Inventory status for one configured host."""

    id: str
    status: HostState
    environment_count: int = 0
    error: str | None = None
    inventory_errors: list[str] = Field(default_factory=list)


class ProjectSummary(BaseModel):
    """Browser-facing configured project."""

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
    """Current local create operation for a project instance."""

    id: str
    host: str
    project: str
    instance: str
    status: OperationStatus
    stage: str
    error: str | None = None


class DashboardResponse(BaseModel):
    """Complete browser state returned by one dashboard request."""

    hosts: list[HostStatus]
    projects: list[ProjectSummary]
    environments: list[DashboardEnvironment]
    operations: list[Operation]
    tokens: dict[GitProvider, bool]
