"""Workspace specifications, runtime contracts, and label-based inventory."""

from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from typing import Annotated, Literal, cast
from urllib.parse import quote

from podman import PodmanClient
from podman.domain.containers import Container
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter

from codespace.resources import LABEL_IMAGE, LABEL_KIND, HostId, Resource, ResourceId
from codespace.runtime.container import (
    ContainerSpec,
    ImagePlatform,
    NonBlankString,
    container_status,
)

type GitProvider = Literal["github", "gitlab"]
type PlatformSelection = Literal["native", "linux/amd64", "linux/arm64"]

CONTAINER_USER = "x"
CONTAINER_UID = 5230
CONTAINER_GID = 5230
CONTAINER_HOME = f"/home/{CONTAINER_USER}"
CONTAINER_STATE_ROOT = "/var/lib/codespace"
WORKSPACE_MOUNT = "/workspace"
UPLOAD_MOUNT = "/upload"
CONTROL_MOUNT = "/run/codespace-control"
WORKSPACE_KEY_SECRET = "codespace_workspace_key"  # noqa: S105 - secret identifier
WORKSPACE_KEY_MOUNT = f"/run/secrets/{WORKSPACE_KEY_SECRET}"
SOURCE_TYPE_ENV = "CODESPACE_SOURCE_TYPE"
CLONE_URL_ENV = "CODESPACE_CLONE_URL"
GIT_ARGS_ENV = "CODESPACE_GIT_ARGS"
CHECKOUT_PATH_ENV = "CODESPACE_CHECKOUT_PATH"
OPEN_PATH_ENV = "CODESPACE_OPEN_PATH"
ENCRYPTED_ENV = "CODESPACE_ENCRYPTED"
ENCRYPTED_PATH_ENV = "CODESPACE_ENCRYPTED_PATH"

LABEL_PROJECT = "codespace.project"
LABEL_WORKSPACE = "codespace.workspace"
LABEL_SOURCE = "codespace.source"
LABEL_REPOSITORY = "codespace.repository"
LABEL_GIT_URL = "codespace.git-url"
LABEL_PLATFORM = "codespace.platform"
LABEL_OPEN_PATH = "codespace.open-path"
LABEL_ENCRYPTED = "codespace.encrypted"
REPOSITORY_RE = re.compile(r"^[\w.-]+(?:/[\w.-]+)+$")
GIT_URL_RE = re.compile(
    r"^(?:ssh://)?[\w.-]+@[a-z0-9][a-z0-9.-]*(?::\d+)?[:/][\w./~-]+?(?:\.git)?/?$"
)
WORKSPACE_SSH_PORT = 22
SSH_HOST_PORT_START = 20_000
SSH_HOST_PORT_COUNT = 10_000


def workspace_path(value: str) -> str:
    path = PurePosixPath(value)
    workspace = PurePosixPath(WORKSPACE_MOUNT)
    if ".." in path.parts:
        raise ValueError("must not contain '..'")
    if not path.is_absolute() or (path != workspace and workspace not in path.parents):
        raise ValueError(f"must be {WORKSPACE_MOUNT} or a path below it")
    return str(path)


type RepositoryPath = Annotated[str, Field(pattern=REPOSITORY_RE.pattern)]
type GitUrl = Annotated[str, Field(pattern=GIT_URL_RE.pattern)]
type TokenString = Annotated[str, Field(pattern=re.compile(r"\S"))]
type WorkspacePath = Annotated[str, AfterValidator(workspace_path)]


def workspace_ssh_host_port(container_name: str) -> int:
    digest_prefix = hashlib.sha256(container_name.encode()).hexdigest()[:4]
    return SSH_HOST_PORT_START + int(digest_prefix, 16) % SSH_HOST_PORT_COUNT


def git_host(provider: GitProvider) -> str:
    return {"github": "github.com", "gitlab": "gitlab.com"}[provider]


class ProviderSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: GitProvider
    repository: RepositoryPath
    args: list[NonBlankString] = Field(default_factory=list)

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
    args: list[NonBlankString] = Field(default_factory=list)

    @property
    def clone_url(self) -> str:
        return self.url

    @property
    def checkout_name(self) -> str:
        return re.split(r"[/:]", self.url.rstrip("/").removesuffix(".git"))[-1]


class EmptySource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["empty"]


type Source = Annotated[ProviderSource | GitSource | EmptySource, Field(discriminator="type")]
_SOURCE: TypeAdapter[Source] = TypeAdapter(Source)


WorkspaceContainerSpec = ContainerSpec


class WorkspaceMetadata(BaseModel):
    """Workspace identity and metadata shared by desired and deployed state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    project: ResourceId
    workspace: ResourceId
    host: HostId
    source: Source
    image: str
    open_path: WorkspacePath
    encrypted: bool

    @property
    def resource(self) -> Resource:
        return Resource(self.host, self.workspace, self.project)

    @property
    def id(self) -> str:
        return self.resource.id

    @property
    def container_name(self) -> str:
        return self.resource.container_name

    @property
    def ssh_host_port(self) -> int:
        return workspace_ssh_host_port(self.container_name)

    @property
    def ssh_alias(self) -> str:
        return f"{self.container_name}-{self.host}"


class WorkspaceSpec(WorkspaceMetadata):
    """Resolved Project placement and one requested Workspace identity."""

    platform: ImagePlatform | None
    container: WorkspaceContainerSpec
    checkout_path: WorkspacePath

    def resolve_data_path(self, data_path: str) -> WorkspaceContainerSpec:
        volumes = [volume.resolve_data_path(data_path) for volume in self.container.volumes]
        if self.encrypted:
            encrypted_workspace_target = self.container.environment[ENCRYPTED_PATH_ENV]
            volumes = [
                volume.model_copy(update={"target": encrypted_workspace_target})
                if volume.target == WORKSPACE_MOUNT
                else volume
                for volume in volumes
            ]
        return self.container.model_copy(update={"volumes": volumes})

    def data_directories(self, data_path: str) -> list[str]:
        resolved = self.resolve_data_path(data_path)
        return [
            actual.source
            for configured, actual in zip(self.container.volumes, resolved.volumes, strict=True)
            if configured.uses_resource_data
        ]

    def labels(self) -> dict[str, str]:
        labels = {
            **self.resource.labels,
            LABEL_SOURCE: self.source.type,
            LABEL_IMAGE: self.image,
            LABEL_PLATFORM: self.platform or "native",
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
            **self.model_dump(exclude={"platform", "container", "checkout_path"}),
            platform=self.platform or "native",
            container_id=container_id,
            status=status,
        )


class RepoGitState(BaseModel):
    """Read-only pre-delete state for a Git-backed Workspace."""

    model_config = ConfigDict(extra="forbid", strict=True)

    unpushed: bool
    uncommitted: bool
    detail: list[str]


class Workspace(WorkspaceMetadata):
    """One actual Workspace container read from Podman labels."""

    platform: PlatformSelection
    container_id: str
    status: str


def list_workspaces(client: PodmanClient, host: str) -> list[Workspace]:
    return sorted(
        (
            read_workspace(container, host)
            for container in client.containers.list(
                all=True, filters={"label": f"{LABEL_KIND}=workspace"}
            )
        ),
        key=lambda item: (item.project, item.workspace),
    )


def read_workspace(container: Container, host: str) -> Workspace:
    labels = container.labels
    source = {"type": labels[LABEL_SOURCE]}
    for field, label in (("repository", LABEL_REPOSITORY), ("url", LABEL_GIT_URL)):
        if label in labels:
            source[field] = labels[label]
    actual = Workspace(
        project=labels[LABEL_PROJECT],
        workspace=labels[LABEL_WORKSPACE],
        host=host,
        source=_SOURCE.validate_python(source),
        image=labels[LABEL_IMAGE],
        platform=cast("PlatformSelection", labels[LABEL_PLATFORM]),
        open_path=labels[LABEL_OPEN_PATH],
        encrypted={"true": True, "false": False}[labels[LABEL_ENCRYPTED]],
        container_id=container.id,
        status=container_status(container),
    )
    if container.name != actual.container_name:
        raise RuntimeError(
            f"workspace container {container.name!r} does not match its labels; "
            f"expected name {actual.container_name!r}"
        )
    return actual


def editor_url(alias: str, open_path: str, *, scheme: str = "trae") -> str:
    return (
        f"{scheme}://vscode-remote/ssh-remote+{quote(alias, safe='')}"
        f"{quote(open_path, safe='/')}?windowId=_blank&fullscreen=true"
    )
