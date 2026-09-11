"""Workspace identities, runtime contracts, and inventory models."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from codespace.runtime.container import ContainerSpec, ImagePlatform

type GitProvider = Literal["github", "gitlab"]
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
WORKSPACE_KEY_SECRET = "codespace_workspace_key"  # noqa: S105 - secret identifier
WORKSPACE_KEY_MOUNT = f"/run/secrets/{WORKSPACE_KEY_SECRET}"
SOURCE_TYPE_ENV = "CODESPACE_SOURCE_TYPE"
CLONE_URL_ENV = "CODESPACE_CLONE_URL"
CHECKOUT_PATH_ENV = "CODESPACE_CHECKOUT_PATH"
OPEN_PATH_ENV = "CODESPACE_OPEN_PATH"
ENCRYPTED_ENV = "CODESPACE_ENCRYPTED"

LABEL_KIND = "codespace.kind"
LABEL_PROJECT = "codespace.project"
LABEL_WORKSPACE = "codespace.workspace"
LABEL_SOURCE = "codespace.source"
LABEL_REPOSITORY = "codespace.repository"
LABEL_GIT_URL = "codespace.git-url"
LABEL_IMAGE = "codespace.image"
LABEL_PLATFORM = "codespace.platform"
LABEL_OPEN_PATH = "codespace.open-path"
LABEL_ENCRYPTED = "codespace.encrypted"
WORKSPACE_KIND = "workspace"

RESOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}$")
REPOSITORY_RE = re.compile(r"^[\w.-]+(?:/[\w.-]+)+$")
GIT_URL_RE = re.compile(
    r"^(?:ssh://)?[\w.-]+@[a-z0-9][a-z0-9.-]*(?::\d+)?[:/][\w./~-]+?(?:\.git)?/?$"
)
WORKSPACE_SSH_PORT = 22
SSH_HOST_PORT_START = 20_000
SSH_HOST_PORT_COUNT = 10_000


def _not_blank_token(value: str) -> str:
    if not value.strip():
        raise ValueError("token must not be blank")
    return value


def workspace_path(value: str) -> str:
    path = PurePosixPath(value)
    workspace = PurePosixPath(WORKSPACE_MOUNT)
    if ".." in path.parts:
        raise ValueError("must not contain '..'")
    if not path.is_absolute() or (path != workspace and workspace not in path.parents):
        raise ValueError(f"must be {WORKSPACE_MOUNT} or a path below it")
    return str(path)


type ResourceId = Annotated[str, Field(pattern=RESOURCE_ID_RE.pattern)]
type HostId = Annotated[str, Field(pattern=HOST_RE.pattern)]
type RepositoryPath = Annotated[str, Field(pattern=REPOSITORY_RE.pattern)]
type GitUrl = Annotated[str, Field(pattern=GIT_URL_RE.pattern)]
type TokenString = Annotated[str, AfterValidator(_not_blank_token)]
type WorkspacePath = Annotated[str, AfterValidator(workspace_path)]


def workspace_identity(host: str, project: str, workspace: str) -> str:
    return f"codespace-workspace_{host}_{project}_{workspace}"


def workspace_ssh_host_port(identity: str) -> int:
    digest_prefix = hashlib.sha256(identity.encode()).hexdigest()[:4]
    return SSH_HOST_PORT_START + int(digest_prefix, 16) % SSH_HOST_PORT_COUNT


def platform_label(platform: ImagePlatform | None) -> PlatformSelection:
    return platform if platform is not None else "native"


def git_host(provider: GitProvider) -> str:
    match provider:
        case "github":
            return "github.com"
        case "gitlab":
            return "gitlab.com"


class ProviderSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: GitProvider
    repository: RepositoryPath

    @property
    def clone_url(self) -> str:
        return f"git@{git_host(self.type)}:{self.repository}.git"

    @property
    def checkout_name(self) -> str:
        return self.repository.rsplit("/", 1)[-1].removesuffix(".git")


class GitSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["git"]
    url: GitUrl

    @property
    def clone_url(self) -> str:
        return self.url

    @property
    def checkout_name(self) -> str:
        trimmed = self.url.rstrip("/").removesuffix(".git")
        return re.split(r"[/:]", trimmed)[-1]


class EmptySource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["empty"]

    @property
    def clone_url(self) -> None:
        return None

    @property
    def checkout_name(self) -> None:
        return None


type Source = Annotated[ProviderSource | GitSource | EmptySource, Field(discriminator="type")]


class WorkspaceContainerSpec(ContainerSpec):
    """Resolved container contract for every Workspace."""

    network_mode: Literal["bridge"] = "bridge"


@dataclass(frozen=True, slots=True)
class WorkspaceSpec:
    """Resolved Project placement and one requested Workspace identity."""

    project: str
    workspace: str
    host: str
    source: Source
    platform: ImagePlatform | None
    image: str
    container: WorkspaceContainerSpec
    checkout_path: WorkspacePath
    open_path: WorkspacePath
    encrypted: bool

    @property
    def identity(self) -> str:
        return workspace_identity(self.host, self.project, self.workspace)

    @property
    def ssh_host_port(self) -> int:
        return workspace_ssh_host_port(self.identity)

    @property
    def platform_label(self) -> PlatformSelection:
        return platform_label(self.platform)

    def labels(self) -> dict[str, str]:
        labels = {
            LABEL_KIND: WORKSPACE_KIND,
            LABEL_PROJECT: self.project,
            LABEL_WORKSPACE: self.workspace,
            LABEL_SOURCE: self.source.type,
            LABEL_IMAGE: self.image,
            LABEL_PLATFORM: self.platform_label,
            LABEL_OPEN_PATH: self.open_path,
            LABEL_ENCRYPTED: str(self.encrypted).lower(),
        }
        if isinstance(self.source, ProviderSource):
            labels[LABEL_REPOSITORY] = self.source.repository
        if isinstance(self.source, GitSource):
            labels[LABEL_GIT_URL] = self.source.url
        return labels

    def to_workspace(self, container_id: str, *, status: str) -> Workspace:
        return Workspace(
            project=self.project,
            workspace=self.workspace,
            host=self.host,
            source=self.source,
            image=self.image,
            platform=self.platform_label,
            open_path=self.open_path,
            encrypted=self.encrypted,
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

    project: ResourceId
    workspace: ResourceId
    host: HostId
    source: Source
    image: str
    platform: PlatformSelection
    open_path: WorkspacePath
    encrypted: bool
    container_id: str
    status: str

    @property
    def id(self) -> str:
        return workspace_identity(self.host, self.project, self.workspace)

    @property
    def ssh_host_port(self) -> int:
        return workspace_ssh_host_port(self.id)

    @property
    def ssh_alias(self) -> str:
        return (
            f"codespace-workspace-{self.ssh_host_port}_{self.host}_{self.project}_{self.workspace}"
        )


def editor_url(alias: str, open_path: str, *, scheme: str = "trae") -> str:
    return (
        f"{scheme}://vscode-remote/ssh-remote+{quote(alias, safe='')}"
        f"{quote(open_path, safe='/')}?windowId=_blank&fullscreen=true"
    )
