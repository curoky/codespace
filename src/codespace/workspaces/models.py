"""Workspace identities, runtime contracts, and inventory models."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from codespace.runtime.container import ContainerSpec, ImagePlatform

type GitProvider = Literal["github", "gitlab"]
type SourceType = Literal["github", "gitlab", "git", "empty"]
type PlatformSelection = Literal["native", "linux/amd64", "linux/arm64"]

CONTAINER_USER = "x"
CONTAINER_UID = 5230
CONTAINER_GID = 5230
CONTAINER_HOME = f"/home/{CONTAINER_USER}"
WORKSPACE_MOUNT = "/workspace"
WORKSPACE_CIPHER_MOUNT = "/workspace.enc"
UPLOAD_MOUNT = "/upload"
CACHE_MOUNT = "/cache"
CONTROL_MOUNT = "/run/codespace-control"
HOME_CACHE_MOUNTS = (
    (".vscode-server", f"{CONTAINER_HOME}/.vscode-server"),
    (".trae", f"{CONTAINER_HOME}/.trae"),
    (".trae-cn", f"{CONTAINER_HOME}/.trae-cn"),
    (".trae-server", f"{CONTAINER_HOME}/.trae-server"),
    (".trae-cn-server", f"{CONTAINER_HOME}/.trae-cn-server"),
)
WORKSPACE_KEY_SECRET = "codespace_workspace_key"  # noqa: S105 - secret identifier
WORKSPACE_KEY_ENV = "CODESPACE_WORKSPACE_KEY"
SOURCE_TYPE_ENV = "CODESPACE_SOURCE_TYPE"
CLONE_URL_ENV = "CODESPACE_CLONE_URL"
CHECKOUT_PATH_ENV = "CODESPACE_CHECKOUT_PATH"
OPEN_PATH_ENV = "CODESPACE_OPEN_PATH"
SSHD_PORT_ENV = "SSHD_PORT"
SSHD_BIND_ENV = "SSHD_BIND"

LABEL_KIND = "codespace.kind"
LABEL_PROJECT = "codespace.project"
LABEL_WORKSPACE = "codespace.workspace"
LABEL_SOURCE = "codespace.source"
LABEL_REPOSITORY = "codespace.repository"
LABEL_GIT_URL = "codespace.git-url"
LABEL_IMAGE = "codespace.image"
LABEL_PLATFORM = "codespace.platform"
LABEL_SSH_PORT = "codespace.ssh-port"
WORKSPACE_KIND = "workspace"
MANDATORY_LABELS = (
    LABEL_PROJECT,
    LABEL_WORKSPACE,
    LABEL_SOURCE,
    LABEL_IMAGE,
    LABEL_PLATFORM,
    LABEL_SSH_PORT,
)

RESOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}$")
REPOSITORY_RE = re.compile(r"^[\w.-]+(?:/[\w.-]+)+$")
GIT_URL_RE = re.compile(
    r"^(?:ssh://)?[\w.-]+@[a-z0-9][a-z0-9.-]*(?::\d+)?[:/][\w./~-]+?(?:\.git)?/?$"
)
SSH_PORT_START = 20_000
SSH_PORT_COUNT = 10_000


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
type RepositoryPath = Annotated[str, Field(pattern=REPOSITORY_RE.pattern)]
type GitUrl = Annotated[str, Field(pattern=GIT_URL_RE.pattern)]
type NonBlankString = Annotated[str, AfterValidator(_not_blank)]
type TokenString = Annotated[str, AfterValidator(_not_blank_token)]


def workspace_identity(host: str, project: str, workspace: str) -> str:
    return f"codespace-workspace-{host}-{project}-{workspace}"


def workspace_ssh_port(identity: str) -> int:
    digest_prefix = hashlib.sha256(identity.encode()).hexdigest()[:4]
    return SSH_PORT_START + int(digest_prefix, 16) % SSH_PORT_COUNT


def platform_label(platform: ImagePlatform | None) -> PlatformSelection:
    return platform if platform is not None else "native"


def git_host(provider: GitProvider) -> str:
    match provider:
        case "github":
            return "github.com"
        case "gitlab":
            return "gitlab.com"


@dataclass(frozen=True, slots=True)
class WorkspaceSpec:
    """Resolved Project placement and one requested Workspace identity."""

    project: str
    workspace: str
    host: str
    source: SourceType
    repository: str | None
    git_url: str | None
    clone_url: str | None
    platform: ImagePlatform | None
    image: str
    container: ContainerSpec
    checkout_path: str
    open_path: str
    encrypted: bool

    @property
    def identity(self) -> str:
        return workspace_identity(self.host, self.project, self.workspace)

    @property
    def ssh_port(self) -> int:
        return workspace_ssh_port(self.identity)

    @property
    def platform_label(self) -> PlatformSelection:
        return platform_label(self.platform)

    def labels(self) -> dict[str, str]:
        labels = {
            LABEL_KIND: WORKSPACE_KIND,
            LABEL_PROJECT: self.project,
            LABEL_WORKSPACE: self.workspace,
            LABEL_SOURCE: self.source,
            LABEL_IMAGE: self.image,
            LABEL_PLATFORM: self.platform_label,
            LABEL_SSH_PORT: str(self.ssh_port),
        }
        if self.repository is not None:
            labels[LABEL_REPOSITORY] = self.repository
        if self.git_url is not None:
            labels[LABEL_GIT_URL] = self.git_url
        return labels

    def to_workspace(self, container_id: str, *, status: str | None = None) -> Workspace:
        return Workspace(
            id=self.identity,
            project=self.project,
            workspace=self.workspace,
            host=self.host,
            source=self.source,
            repository=self.repository,
            git_url=self.git_url,
            image=self.image,
            platform=self.platform_label,
            ssh_port=self.ssh_port,
            container_id=container_id,
            status=status,
        )


class RepoGitState(BaseModel):
    """Read-only pre-delete state for a Git-backed Workspace."""

    model_config = ConfigDict(extra="forbid")

    unpushed: bool = False
    uncommitted: bool = False
    detail: list[str] = Field(default_factory=list)


class Workspace(BaseModel):
    """One actual Workspace container read from Podman labels."""

    model_config = ConfigDict(extra="forbid")

    id: str
    project: str
    workspace: str
    host: str
    source: SourceType
    repository: str | None = None
    git_url: str | None = None
    image: str
    platform: PlatformSelection
    ssh_port: int
    container_id: str
    status: str | None = None


def editor_url(alias: str, open_path: str, *, scheme: str = "trae") -> str:
    return (
        f"{scheme}://vscode-remote/ssh-remote+{quote(alias, safe='')}"
        f"{quote(open_path, safe='/')}?windowId=_blank&fullscreen=true"
    )
