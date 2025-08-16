"""Codespace resource identity and API models."""

from __future__ import annotations

import hashlib
import re
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, field_validator

type GitProvider = Literal["github", "gitlab"]
type OperationStatus = Literal["queued", "running", "failed"]
type HostState = Literal["online", "offline"]

CONTAINER_USER = "x"
CONTAINER_UID = 5230
WORKSPACE_MOUNT = "/workspace"
WORKSPACE_ROOT = "/var/lib/codespace"
PODMAN_SOCKET = "/run/podman/podman.sock"
SSH_PORT_START = 20_000
SSH_PORT_COUNT = 10_000

RESOURCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
HOST_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,62}$")
REPO_RE = re.compile(r"^[\w.-]+(?:/[\w.-]+)+$")

LABEL_MANAGED = "codespace.managed"
LABEL_PROJECT = "codespace.project"
LABEL_INSTANCE = "codespace.instance"
LABEL_REPO = "codespace.repo"
LABEL_PROVIDER = "codespace.provider"
LABEL_IMAGE = "codespace.image"
LABEL_SSH_PORT = "codespace.ssh-port"


def environment_id(host: str, project: str, instance: str) -> str:
    """Return the deterministic identity shared by all environment resources."""
    return f"codespace-{host}-{project}-{instance}"


def workspace_path(project: str, instance: str) -> str:
    """Return the fixed host workspace path for one environment."""
    return f"{WORKSPACE_ROOT}/{project}/{instance}"


def ssh_port(identity: str) -> int:
    """Map an environment identity to its deterministic reserved SSH port."""
    digest_prefix = hashlib.sha256(identity.encode()).hexdigest()[:4]
    return SSH_PORT_START + int(digest_prefix, 16) % SSH_PORT_COUNT


def deploy_key_title(identity: str) -> str:
    """Return the provider deploy-key title for an environment."""
    return identity


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


def trae_url(alias: str, repo: str, *, scheme: str = "trae") -> str:
    """Build a Trae Remote-SSH deep link for an environment."""
    return (
        f"{scheme}://vscode-remote/ssh-remote+{quote(alias, safe='')}"
        f"{quote(repo_target(repo), safe='/')}?windowId=_blank&fullscreen=true"
    )


class CreateInstanceRequest(BaseModel):
    """Request body for creating one configured project instance."""

    model_config = ConfigDict(extra="forbid")

    instance: str

    @field_validator("instance")
    @classmethod
    def _validate_instance(cls, value: str) -> str:
        if not RESOURCE_ID_RE.fullmatch(value):
            raise ValueError("instance must match ^[a-z0-9][a-z0-9-]{0,31}$")
        return value


class UpdateTokenRequest(BaseModel):
    """Request body for storing a provider token in process memory."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, repr=False)

    @field_validator("token")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("token must not be blank")
        return value


class Environment(BaseModel):
    """A managed development environment discovered from Podman."""

    id: str
    host: str
    project: str
    instance: str
    repo: str
    provider: GitProvider
    image: str
    ssh_port: int
    container_id: str
    status: str | None = None

    @property
    def workspace(self) -> str:
        return workspace_path(self.project, self.instance)


class DashboardEnvironment(BaseModel):
    """Browser-facing environment projection."""

    id: str
    host: str
    project: str
    instance: str
    repo: str
    provider: GitProvider
    image: str
    ssh_port: int
    status: str | None = None
    alias: str
    ssh_command: str
    trae_url: str
    trae_cn_url: str

    @classmethod
    def from_environment(cls, environment: Environment) -> DashboardEnvironment:
        return cls(
            **environment.model_dump(exclude={"container_id"}),
            alias=environment.id,
            ssh_command=f"ssh {environment.id}",
            trae_url=trae_url(environment.id, environment.repo),
            trae_cn_url=trae_url(environment.id, environment.repo, scheme="trae-cn"),
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
    provider: GitProvider
    repo: str
    image: str
    description: str | None = None


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
