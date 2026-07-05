"""Pydantic models for the local Web GUI API."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from codespace import shared

WebOperationStatus = Literal["queued", "running", "succeeded", "failed"]


class ConfigDefaultsSummary(BaseModel):
    image: str


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
    image: str | None = None


class ConfigSummary(BaseModel):
    default_agent: str
    defaults: ConfigDefaultsSummary
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
    template: str
    instance: str
    alias: str | None = None
    ssh_host: str
    port: int
    user: str
    status: str | None = None
    raw_ssh_command: str
    trae_url: str


class CreateCodespaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo: str
    provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER
    template: str = shared.DEFAULT_TEMPLATE
    instance: str = shared.DEFAULT_INSTANCE
    image: str


class CreateCodespaceResponse(BaseModel):
    operation_id: str


class UpdateProviderTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, repr=False)


class ProviderTokenStatus(BaseModel):
    has_token: bool = False


class TokenStatusResponse(BaseModel):
    github: ProviderTokenStatus = Field(default_factory=ProviderTokenStatus)
    gitlab: ProviderTokenStatus = Field(default_factory=ProviderTokenStatus)


class WebOperation(BaseModel):
    id: str
    agent_id: str
    alias: str
    repo: str
    provider: shared.GitProvider
    template: str
    instance: str
    status: WebOperationStatus
    stage: str
    error: str | None = None
    created_at: float
    updated_at: float


class DashboardResponse(BaseModel):
    agents: list[AgentStatus]
    codespaces: list[DashboardCodespace]
    operations: list[WebOperation]


class ClearOperationsResponse(BaseModel):
    operations: list[WebOperation]
