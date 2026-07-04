"""Local FastAPI Web GUI for managing codespaces across multiple agents."""

import builtins
import logging
import secrets
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock, Thread
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from codespace import shared
from codespace.client import ssh_config
from codespace.client.config import (
    WebConfig,
    default_git_ssh_host,
    github_token,
    gitlab_token,
    is_inline_github_token,
    is_inline_gitlab_token,
    load_config,
    token_for_provider,
)
from codespace.client.service import (
    CodespaceService,
    CreateCodespaceInput,
    DeleteCodespaceResult,
    instance_alias,
)

WebOperationStatus = Literal["queued", "running", "succeeded", "failed"]
STATIC_DIR = Path(__file__).parent / "static"
logger = logging.getLogger(__name__)
GIT_ENV_MISSING_MESSAGE = (
    "{provider} token is not available in the Web GUI process; set {token_env} "
    "before starting `python -m codespace.client web`, or configure {config_key}.token_env "
    "in config.yaml."
)
INLINE_GITHUB_AUTH_SOURCE_LABEL = "inline GitHub credential"
INLINE_GITLAB_AUTH_SOURCE_LABEL = "inline GitLab credential"


class ConfigDefaultsSummary(BaseModel):
    image: str


class ConfigGithubSummary(BaseModel):
    token_env: str
    has_token: bool
    inline_token: bool = False


class ConfigGitlabSummary(BaseModel):
    token_env: str
    api_url: str
    ssh_host: str
    has_token: bool
    inline_token: bool = False


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


class OperationStore:
    """Thread-safe in-memory store for Web GUI operations."""

    def __init__(self) -> None:
        self._operations: dict[str, WebOperation] = {}
        self._lock = Lock()

    def create(self, *, agent_id: str, req: CreateCodespaceRequest) -> WebOperation:
        now = time.time()
        operation = WebOperation(
            id=secrets.token_hex(6),
            agent_id=agent_id,
            alias=instance_alias(agent_id, req.template, req.instance),
            repo=req.repo,
            provider=req.provider,
            git_ssh_host=req.git_ssh_host,
            template=req.template,
            instance=req.instance,
            status="queued",
            stage="queued",
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            self._operations[operation.id] = operation
        return operation

    def get(self, operation_id: str) -> WebOperation | None:
        with self._lock:
            return self._operations.get(operation_id)

    def list(self) -> list[WebOperation]:
        with self._lock:
            return sorted(self._operations.values(), key=lambda op: op.created_at, reverse=True)

    def prune_completed(self) -> builtins.list[WebOperation]:
        """Remove non-busy operations and return the remaining operations."""
        with self._lock:
            self._operations = {
                operation_id: operation
                for operation_id, operation in self._operations.items()
                if operation.status in {"queued", "running"}
            }
            return sorted(self._operations.values(), key=lambda op: op.created_at, reverse=True)

    def update(
        self,
        operation_id: str,
        *,
        status: WebOperationStatus | None = None,
        stage: str | None = None,
        codespace: shared.Codespace | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            operation = self._operations[operation_id]
            self._operations[operation_id] = operation.model_copy(
                update={
                    key: value
                    for key, value in {
                        "status": status,
                        "stage": stage,
                        "codespace": codespace,
                        "error": error,
                        "updated_at": time.time(),
                    }.items()
                    if value is not None
                }
            )


def create_app(config_path: str | Path | None = None) -> FastAPI:
    """Build the local Web GUI FastAPI app."""
    config = load_config(config_path)
    service = CodespaceService(config)
    operations = OperationStore()

    @asynccontextmanager
    async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            service.close()

    app = FastAPI(title="codespace-web", lifespan=_lifespan)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.exception_handler(HTTPException)
    def _render_error(_request: object, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=shared.ErrorResponse(error=str(exc.detail)).model_dump(),
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/config")
    def get_config() -> ConfigSummary:
        return _config_summary(config)

    @app.get("/api/dashboard")
    def get_dashboard() -> DashboardResponse:
        agent_results = service.list_all_agents()
        agent_statuses: list[AgentStatus] = []
        codespaces: list[DashboardCodespace] = []
        for result in agent_results:
            profile = result.agent
            agent_statuses.append(
                AgentStatus(
                    id=profile.id,
                    agent_url=profile.agent_url,
                    ssh_host=profile.ssh_host,
                    ssh_proxy_host=profile.ssh_proxy_host,
                    ssh_proxy=profile.ssh_proxy,
                    status="online" if result.online else "offline",
                    error=result.error,
                    codespace_count=len(result.codespaces),
                )
            )
            for cs in result.codespaces:
                codespaces.append(_dashboard_codespace(profile.id, profile.ssh_host, cs))
        return DashboardResponse(
            agents=agent_statuses,
            codespaces=codespaces,
            operations=operations.list(),
        )

    @app.post("/api/agents/{agent_id}/codespaces")
    def create_codespace(agent_id: str, req: CreateCodespaceRequest) -> CreateCodespaceResponse:
        if agent_id not in config.agents:
            raise HTTPException(status_code=404, detail="agent not found")
        token = token_for_provider(config, req.provider)
        if not token:
            token_env = (
                config.github.token_env if req.provider == "github" else config.gitlab.token_env
            )
            message = GIT_ENV_MISSING_MESSAGE.format(
                provider="GitHub" if req.provider == "github" else "GitLab",
                token_env=token_env,
                config_key=req.provider,
            )
            logger.warning("Rejecting create codespace request for agent %s: %s", agent_id, message)
            raise HTTPException(status_code=400, detail=message)
        operation = operations.create(agent_id=agent_id, req=req)
        Thread(
            target=_run_create_operation,
            args=(operations, service, operation.id, agent_id, req, token),
            daemon=True,
        ).start()
        return CreateCodespaceResponse(operation_id=operation.id)

    @app.get("/api/operations/{operation_id}")
    def get_operation(operation_id: str) -> WebOperation:
        operation = operations.get(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="operation not found")
        return operation

    @app.delete("/api/operations")
    def clear_operations() -> ClearOperationsResponse:
        return ClearOperationsResponse(operations=operations.prune_completed())

    @app.delete("/api/agents/{agent_id}/codespaces/{codespace_id}")
    def delete_codespace(
        agent_id: str,
        codespace_id: str,
        purge: bool = Query(False),
        repo: str | None = Query(None),
    ) -> DeleteCodespaceResult:
        provider = _provider_for_delete(config, agent_id, codespace_id, repo)
        token = token_for_provider(config, provider)
        try:
            if provider == shared.DEFAULT_GIT_PROVIDER:
                return service.delete_codespace(
                    agent_id, codespace_id, token=token, repo=repo, purge=purge
                )
            return service.delete_codespace(
                agent_id, codespace_id, token=token, repo=repo, provider=provider, purge=purge
            )
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


def _config_summary(config: WebConfig) -> ConfigSummary:
    return ConfigSummary(
        default_agent=config.defaults.agent,
        defaults=ConfigDefaultsSummary(image=config.defaults.image),
        github=ConfigGithubSummary(
            token_env=_safe_github_token_env_label(config),
            has_token=github_token(config) is not None,
            inline_token=is_inline_github_token(config.github.token_env),
        ),
        gitlab=ConfigGitlabSummary(
            token_env=_safe_gitlab_token_env_label(config),
            api_url=config.gitlab.api_url,
            ssh_host=config.gitlab.ssh_host,
            has_token=gitlab_token(config) is not None,
            inline_token=is_inline_gitlab_token(config.gitlab.token_env),
        ),
        agents=[
            ConfigAgentSummary(
                id=agent.id,
                agent_url=agent.agent_url,
                ssh_host=agent.ssh_host,
                ssh_proxy_host=agent.ssh_proxy_host,
                ssh_proxy=agent.ssh_proxy,
            )
            for agent in config.agents.values()
        ],
        templates=[
            ConfigTemplateSummary(
                id=template.id,
                description=template.description,
                agent=template.agent,
                provider=template.provider,
                repo=template.repo,
                git_ssh_host=template.git_ssh_host
                or default_git_ssh_host(config, template.provider),
                image=template.image,
            )
            for template in config.templates.values()
        ],
    )


def _safe_github_token_env_label(config: WebConfig) -> str:
    """Return a UI-safe GitHub token source label without leaking inline tokens."""
    if is_inline_github_token(config.github.token_env):
        return INLINE_GITHUB_AUTH_SOURCE_LABEL
    return config.github.token_env


def _safe_gitlab_token_env_label(config: WebConfig) -> str:
    """Return a UI-safe GitLab token source label without leaking inline tokens."""
    if is_inline_gitlab_token(config.gitlab.token_env):
        return INLINE_GITLAB_AUTH_SOURCE_LABEL
    return config.gitlab.token_env


def _dashboard_codespace(agent_id: str, ssh_host: str, cs: shared.Codespace) -> DashboardCodespace:
    entry = ssh_config.find_entry(codespace_id=cs.id, agent_id=agent_id)
    alias = entry.alias if entry else None
    raw_ssh_command = f"ssh {cs.user}@{ssh_host} -p {cs.port}"
    remote_authority = alias if alias else f"{cs.user}@{ssh_host}:{cs.port}"
    return DashboardCodespace(
        agent_id=agent_id,
        id=cs.id,
        repo=cs.repo,
        provider=cs.provider,
        git_ssh_host=cs.git_ssh_host,
        template=cs.template,
        instance=cs.instance,
        alias=alias,
        ssh_host=ssh_host,
        port=cs.port,
        user=cs.user,
        status=cs.status,
        ssh_command=f"ssh {alias}" if alias else raw_ssh_command,
        raw_ssh_command=raw_ssh_command,
        trae_url=_trae_remote_ssh_url(remote_authority, repo=cs.repo),
        has_local_alias=alias is not None,
    )


def _provider_for_delete(
    config: WebConfig, agent_id: str, codespace_id: str, repo: str | None
) -> shared.GitProvider:
    entry = ssh_config.find_entry(codespace_id=codespace_id, agent_id=agent_id)
    if entry is not None:
        return entry.provider
    if repo is not None:
        for template in config.templates.values():
            if template.repo == repo:
                return template.provider
    return shared.DEFAULT_GIT_PROVIDER


def _repo_workspace_path(repo: str | None = None) -> str:
    """Return the remote path Trae should open for a repo, if known."""
    if repo is None:
        return shared.WORKSPACE_MOUNT
    repo_name = repo.rstrip("/").split("/")[-1].removesuffix(".git")
    if not repo_name:
        return shared.WORKSPACE_MOUNT
    return f"{shared.WORKSPACE_MOUNT}/{repo_name}"


def _trae_remote_ssh_url(
    remote_authority: str, repo: str | None = None, *, new_window: bool = True
) -> str:
    """Build a Trae Remote-SSH deep link for a remote authority and optional repo path."""
    remote_path = _repo_workspace_path(repo)
    url = (
        "trae://vscode-remote/ssh-remote+"
        f"{quote(remote_authority, safe='')}"
        f"{quote(remote_path, safe='/')}"
    )
    if new_window:
        return f"{url}?windowId=_blank"
    return url


def _run_create_operation(
    operations: OperationStore,
    service: CodespaceService,
    operation_id: str,
    agent_id: str,
    req: CreateCodespaceRequest,
    token: str,
) -> None:
    def _progress(stage: str) -> None:
        operations.update(operation_id, status="running", stage=stage)

    try:
        operations.update(operation_id, status="running", stage="starting")
        cs = service.create_codespace(
            agent_id,
            CreateCodespaceInput.model_validate(req.model_dump()),
            token=token,
            progress=_progress,
        )
        operations.update(operation_id, status="succeeded", stage="ready", codespace=cs)
    except Exception as exc:
        operations.update(operation_id, status="failed", stage="failed", error=str(exc))
