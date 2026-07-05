"""Pydantic models for the local Web GUI API."""

from typing import Literal

from pydantic import BaseModel, Field

from codespace import shared

WebOperationStatus = Literal["queued", "running", "succeeded", "failed"]


class ConfigDefaultsSummary(BaseModel):
    image: str


class ConfigGithubSummary(BaseModel):
    token_env: str
    has_token: bool


class ConfigGitlabSummary(BaseModel):
    token_env: str
    api_url: str
    ssh_host: str
    has_token: bool


class ConfigAgentSummary(BaseModel):
    id: str
    agent_url: str
    ssh_host: str
    ssh_proxy_host: str | None = None
    ssh_proxy: bool = False


class ConfigTemplateSummary(BaseModel):
    id: str
    description: str | None = None
    agent: str | None = None
    provider: shared.GitProvider
    repo: str
    git_ssh_host: str
    image: str | None = None


class ConfigSummary(BaseModel):
    default_agent: str
    defaults: ConfigDefaultsSummary
    github: ConfigGithubSummary
    gitlab: ConfigGitlabSummary
    agents: list[ConfigAgentSummary]
    templates: list[ConfigTemplateSummary]


class AgentStatus(BaseModel):
    id: str
    agent_url: str
    ssh_host: str
    ssh_proxy_host: str | None = None
    ssh_proxy: bool = False
    status: Literal["online", "offline"]
    error: str | None = None
    codespace_count: int = 0


class DashboardCodespace(BaseModel):
    agent_id: str
    id: str
    repo: str
    provider: shared.GitProvider
    git_ssh_host: str
    template: str
    instance: str
    alias: str | None = None
    ssh_host: str
    port: int
    user: str
    status: str | None = None
    ssh_command: str
    raw_ssh_command: str
    trae_url: str
    has_local_alias: bool


class CreateCodespaceRequest(BaseModel):
    repo: str
    provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER
    git_ssh_host: str | None = None
    template: str = shared.DEFAULT_TEMPLATE
    instance: str = shared.DEFAULT_INSTANCE
    image: str
    env: dict[str, str] = Field(default_factory=dict)


class CreateCodespaceResponse(BaseModel):
    operation_id: str


class WebOperation(BaseModel):
    id: str
    agent_id: str
    alias: str
    repo: str
    provider: shared.GitProvider
    git_ssh_host: str | None = None
    template: str
    instance: str
    status: WebOperationStatus
    stage: str
    codespace: shared.Codespace | None = None
    error: str | None = None
    created_at: float
    updated_at: float


class DashboardResponse(BaseModel):
    agents: list[AgentStatus]
    codespaces: list[DashboardCodespace]
    operations: list[WebOperation]


class ClearOperationsResponse(BaseModel):
    operations: list[WebOperation]
