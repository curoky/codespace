"""HTTP request, response, and Dashboard models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from codespace.operations import Operation
from codespace.runtime.container import ImagePlatform
from codespace.workspaces.models import (
    GitProvider,
    HostId,
    RepoGitState,
    ResourceId,
    SourceType,
    TokenString,
    Workspace,
    editor_url,
)


class CreateWorkspaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: HostId
    workspace: ResourceId


class UpdateTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: TokenString = Field(repr=False)


class ContainerLogsResult(BaseModel):
    logs: str


class DeleteWorkspaceResult(BaseModel):
    deleted: bool
    data_removed: bool = False
    state: RepoGitState = Field(default_factory=RepoGitState)


class RemoveServiceResult(BaseModel):
    removed: bool
    data_removed: bool = False


class HostStatus(BaseModel):
    id: str
    status: Literal["online", "offline"]
    workspace_count: int = 0
    error: str | None = None


class ProjectHostSummary(BaseModel):
    name: str
    platform: ImagePlatform | None = None
    image: str


class ProjectSummary(BaseModel):
    id: str
    hosts: list[ProjectHostSummary]
    source: SourceType
    repository: str | None = None
    git_url: str | None = None
    description: str | None = None
    checkout_path: str
    open_path: str


class DashboardWorkspace(BaseModel):
    id: str
    project: str
    workspace: str
    host: str
    source: SourceType
    repository: str | None = None
    git_url: str | None = None
    image: str
    platform: str
    ssh_port: int
    status: str | None = None
    alias: str
    ssh_command: str
    trae_url: str
    trae_cn_url: str

    @classmethod
    def from_workspace(cls, workspace: Workspace, open_path: str) -> DashboardWorkspace:
        return cls(
            **workspace.model_dump(exclude={"container_id"}),
            alias=workspace.id,
            ssh_command=f"ssh {workspace.id}",
            trae_url=editor_url(workspace.id, open_path),
            trae_cn_url=editor_url(workspace.id, open_path, scheme="trae-cn"),
        )


class ServiceHostStatus(BaseModel):
    host: str
    state: Literal["running", "stopped", "missing"]
    image: str
    status: str | None = None
    container_id: str | None = None
    error: str | None = None


class ServiceSummary(BaseModel):
    id: str
    hosts: list[ServiceHostStatus]


class DashboardResponse(BaseModel):
    hosts: list[HostStatus]
    projects: list[ProjectSummary]
    workspaces: list[DashboardWorkspace]
    services: list[ServiceSummary]
    operations: list[Operation]
    tokens: dict[GitProvider, bool]
