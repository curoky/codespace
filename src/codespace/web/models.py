"""HTTP request, response, and Dashboard models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from codespace.operations import Operation
from codespace.runtime.container import ImagePlatform
from codespace.services.models import Service
from codespace.workspaces.models import (
    GitProvider,
    HostId,
    RepoGitState,
    ResourceId,
    Source,
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
    source: Source
    description: str | None = None
    open_path: str
    tunnel_ports: list[int]


class DashboardWorkspace(Workspace):
    container_id: str = Field(exclude=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def ssh_command(self) -> str:
        return f"ssh {self.id}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def trae_url(self) -> str:
        return editor_url(self.id, self.open_path)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def trae_cn_url(self) -> str:
        return editor_url(self.id, self.open_path, scheme="trae-cn")


class ServiceHostStatus(BaseModel):
    host: str
    desired_image: str
    container: Service | None


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
