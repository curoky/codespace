"""Reusable client-side orchestration for CLI and Web GUI."""

import contextlib
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import httpx
from github import GithubException
from pydantic import BaseModel, Field

from codespace import shared
from codespace.client import github, ssh_config
from codespace.client.config import AgentProfile, WebConfig

KEY_DIR = Path.home() / ".ssh" / "codespace"
HTTP_TIMEOUT = 30.0
CREATE_POLL_INTERVAL = 2.0
ProgressCallback = Callable[[str], None]


class ServiceError(RuntimeError):
    """Base error raised by client service orchestration."""


class AgentListResult(BaseModel):
    """Result of listing one agent."""

    agent: AgentProfile
    online: bool
    codespaces: list[shared.Codespace] = Field(default_factory=list)
    error: str | None = None


class CreateCodespaceInput(BaseModel):
    """Input for service-level create orchestration."""

    repo: str
    workspace: str = shared.DEFAULT_WORKSPACE
    alias: str
    image: str
    user: str = shared.DEFAULT_CONTAINER_USER
    extra_repos: list[str] = Field(default_factory=list)


class DeleteCodespaceResult(BaseModel):
    """Result returned after deleting a codespace."""

    ok: bool = True
    workspace_removed: bool = False
    warning: str | None = None


def default_alias(agent_id: str, repo: str, workspace: str) -> str:
    """Default Web GUI alias, namespaced by agent id."""
    return f"{agent_id}-{repo.split('/')[-1]}-{workspace}"


def request(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    """Perform an HTTP request and return ``(status, parsed_json)``."""
    try:
        resp = httpx.request(method, url, json=body, timeout=HTTP_TIMEOUT)
    except httpx.RequestError as exc:
        raise ServiceError(f"cannot reach agent: {exc}") from exc
    try:
        return resp.status_code, (resp.json() if resp.content else {})
    except ValueError:
        return resp.status_code, {"error": resp.text or resp.reason_phrase}


def ensure_login_key(alias: str) -> str:
    """Ensure a passwordless ed25519 login keypair exists; return the pubkey."""
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    key_path = KEY_DIR / alias
    pub_path = KEY_DIR / f"{alias}.pub"
    if not key_path.exists():
        subprocess.run(  # noqa: S603
            ["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", ""],  # noqa: S607
            check=True,
            capture_output=True,
        )
    return pub_path.read_text(encoding="utf-8").strip()


def remove_login_key(alias: str) -> None:
    """Delete the local login keypair for ``alias``."""
    for path in (KEY_DIR / alias, KEY_DIR / f"{alias}.pub"):
        path.unlink(missing_ok=True)


def revoke_quietly(token: str, repo: str, cs_id: str) -> None:
    """Best-effort deploy-key revocation used during create rollback."""
    with contextlib.suppress(GithubException):
        github.delete_deploy_key(token, repo, cs_id)


def delete_remote(agent_url: str, cs_id: str, *, purge: bool = False) -> shared.DeleteResponse:
    """Delete a codespace container on an agent."""
    url = f"{agent_url.rstrip('/')}/codespaces/{cs_id}"
    if purge:
        url += "?purge=true"
    status, data = request("DELETE", url)
    if status != 200:
        raise ServiceError(data.get("error", f"agent returned HTTP {status}"))
    return shared.DeleteResponse.model_validate(data)


class CodespaceService:
    """Client-side operations shared by CLI and Web GUI."""

    def __init__(self, config: WebConfig | None = None) -> None:
        self.config = config

    def agent(self, agent_id: str) -> AgentProfile:
        """Return an agent profile by id."""
        if self.config is None or agent_id not in self.config.agents:
            raise ServiceError(f"unknown agent: {agent_id}")
        return self.config.agents[agent_id]

    def list_agent_codespaces(self, agent_id: str) -> AgentListResult:
        """List codespaces for one configured agent, converting errors to offline results."""
        profile = self.agent(agent_id)
        try:
            status, data = request("GET", f"{profile.agent_url}/codespaces")
            if status != 200:
                return AgentListResult(
                    agent=profile,
                    online=False,
                    error=data.get("error", f"agent returned HTTP {status}"),
                )
            return AgentListResult(
                agent=profile,
                online=True,
                codespaces=[shared.Codespace.model_validate(item) for item in data],
            )
        except Exception as exc:
            return AgentListResult(agent=profile, online=False, error=str(exc))

    def list_all_agents(self) -> list[AgentListResult]:
        """List codespaces for all configured agents."""
        if self.config is None:
            return []
        return [self.list_agent_codespaces(agent_id) for agent_id in self.config.agents]

    def wait_create_operation(
        self,
        agent_url: str,
        operation_id: str,
        *,
        progress: ProgressCallback | None = None,
    ) -> shared.Codespace:
        """Poll an asynchronous agent create operation until completion."""
        url = f"{agent_url.rstrip('/')}/operations/{operation_id}"
        while True:
            status_code, data = request("GET", url)
            if status_code != 200:
                raise ServiceError(data.get("error", f"agent returned HTTP {status_code}"))
            operation = shared.CreateOperation.model_validate(data)
            if progress is not None:
                progress(f"agent: {operation.stage}")
            match operation.status:
                case "queued" | "running":
                    time.sleep(CREATE_POLL_INTERVAL)
                case "succeeded":
                    if operation.codespace is None:
                        raise ServiceError("agent completed create without returning a codespace")
                    return operation.codespace
                case "failed":
                    raise ServiceError(operation.error or "agent failed to provision codespace")

    def create_codespace(
        self,
        agent_id: str,
        req: CreateCodespaceInput,
        *,
        token: str,
        progress: ProgressCallback | None = None,
    ) -> shared.Codespace:
        """Create a codespace on one agent and register local/GitHub state."""
        profile = self.agent(agent_id)
        registered: list[str] = []
        cs: shared.Codespace | None = None
        try:
            if progress is not None:
                progress("preparing login key")
            login_pubkey = ensure_login_key(req.alias)
            extra_repos = [repo for repo in req.extra_repos if repo != req.repo]
            payload = shared.CreateRequest(
                repo=req.repo,
                login_pubkey=login_pubkey,
                image=req.image,
                user=req.user,
                workspace=req.workspace,
                extra_repos=extra_repos,
            )
            if progress is not None:
                progress("requesting agent creation")
            status, data = request("POST", f"{profile.agent_url}/codespaces", payload.model_dump())
            if status != 202:
                raise ServiceError(data.get("error", f"agent returned HTTP {status}"))

            operation = shared.CreateOperation.model_validate(data)
            cs = self.wait_create_operation(profile.agent_url, operation.id, progress=progress)
            if not cs.deploy_keys:
                raise ServiceError("agent did not return any deploy keys")

            for key in cs.deploy_keys:
                if progress is not None:
                    progress(f"registering deploy key: {key.repo}")
                github.register_deploy_key(
                    token, key.repo, cs.id, key.public_openssh, read_only=key.read_only
                )
                registered.append(key.repo)

            if progress is not None:
                progress("writing ssh config")
            ssh_config.upsert(
                req.alias,
                profile.ssh_host,
                cs.port,
                cs.user,
                cs.id,
                [key.repo for key in cs.deploy_keys],
                agent_id=agent_id,
                repo=cs.repo,
            )
            return cs
        except Exception:
            if cs is not None:
                for repo in registered:
                    revoke_quietly(token, repo, cs.id)
                with contextlib.suppress(Exception):
                    delete_remote(profile.agent_url, cs.id)
            remove_login_key(req.alias)
            raise

    def delete_codespace(
        self,
        agent_id: str,
        codespace_id: str,
        *,
        token: str,
        alias: str | None = None,
        repo: str | None = None,
        purge: bool = False,
    ) -> DeleteCodespaceResult:
        """Delete a remote codespace and clean local/GitHub state."""
        profile = self.agent(agent_id)
        entry = ssh_config.find_entry(codespace_id=codespace_id, agent_id=agent_id)
        alias = alias or entry.alias if entry else alias
        repos = ssh_config.get_repos(alias) if alias else []
        warning = None
        if not repos and repo:
            repos = [repo]
            warning = "local alias not found; only main repo deploy key was revoked"
        for repo_name in repos:
            github.delete_deploy_key(token, repo_name, codespace_id)
        resp = delete_remote(profile.agent_url, codespace_id, purge=purge)
        if alias:
            ssh_config.remove(alias)
            remove_login_key(alias)
        return DeleteCodespaceResult(
            ok=resp.ok, workspace_removed=resp.workspace_removed, warning=warning
        )
