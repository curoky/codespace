"""Projection helpers for the local Web GUI API."""

from urllib.parse import quote

from codespace import shared
from codespace.client import ssh_config
from codespace.client.config import WebConfig
from codespace.client.providers import provider_client
from codespace.client.service import AgentListResult
from codespace.client.web_models import (
    AgentStatus,
    ConfigAgentSummary,
    ConfigDefaultsSummary,
    ConfigGithubSummary,
    ConfigGitlabSummary,
    ConfigSummary,
    ConfigTemplateSummary,
    DashboardCodespace,
    DashboardResponse,
    WebOperation,
)


def config_summary(config: WebConfig) -> ConfigSummary:
    """Return a token-safe summary of the Web GUI configuration."""
    github = provider_client(config, "github")
    gitlab = provider_client(config, "gitlab")
    return ConfigSummary(
        default_agent=config.defaults.agent,
        defaults=ConfigDefaultsSummary(image=config.defaults.image),
        github=ConfigGithubSummary(
            token_env=github.token_label,
            has_token=github.token is not None,
        ),
        gitlab=ConfigGitlabSummary(
            token_env=gitlab.token_label,
            api_url=config.gitlab.api_url,
            ssh_host=config.gitlab.ssh_host,
            has_token=gitlab.token is not None,
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
                or provider_client(config, template.provider).ssh_host,
                image=template.image,
            )
            for template in config.templates.values()
        ],
    )


def dashboard_response(
    agent_results: list[AgentListResult], operations: list[WebOperation]
) -> DashboardResponse:
    """Project agent list results and operation state into the dashboard payload."""
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
            codespaces.append(dashboard_codespace(profile.id, profile.ssh_host, cs))
    return DashboardResponse(
        agents=agent_statuses,
        codespaces=codespaces,
        operations=operations,
    )


def dashboard_codespace(agent_id: str, ssh_host: str, cs: shared.Codespace) -> DashboardCodespace:
    """Project an agent codespace into a Web dashboard row."""
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
        trae_url=trae_remote_ssh_url(remote_authority, repo=cs.repo),
        has_local_alias=alias is not None,
    )


def provider_for_delete(
    config: WebConfig, agent_id: str, codespace_id: str, repo: str | None
) -> shared.GitProvider:
    """Infer the git provider to use for deploy-key cleanup during delete."""
    entry = ssh_config.find_entry(codespace_id=codespace_id, agent_id=agent_id)
    if entry is not None:
        return entry.provider
    if repo is not None:
        for template in config.templates.values():
            if template.repo == repo:
                return template.provider
    return shared.DEFAULT_GIT_PROVIDER


def repo_workspace_path(repo: str | None = None) -> str:
    """Return the remote path Trae should open for a repo, if known."""
    if repo is None:
        return shared.WORKSPACE_MOUNT
    repo_name = repo.rstrip("/").split("/")[-1].removesuffix(".git")
    if not repo_name:
        return shared.WORKSPACE_MOUNT
    return f"{shared.WORKSPACE_MOUNT}/{repo_name}"


def trae_remote_ssh_url(
    remote_authority: str,
    repo: str | None = None,
    *,
    new_window: bool = True,
    fullscreen: bool = True,
) -> str:
    """Build a Trae Remote-SSH deep link for a remote authority and optional repo path."""
    remote_path = repo_workspace_path(repo)
    url = (
        "trae://vscode-remote/ssh-remote+"
        f"{quote(remote_authority, safe='')}"
        f"{quote(remote_path, safe='/')}"
    )
    query: list[str] = []
    if new_window:
        query.append("windowId=_blank")
    if fullscreen:
        query.append("fullscreen=true")
    if query:
        return f"{url}?{'&'.join(query)}"
    return url
