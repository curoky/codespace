"""Reusable client-side orchestration for the local Web GUI."""

import contextlib
import ipaddress
import socket
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from pydantic import BaseModel, ConfigDict, Field
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    stop_after_delay,
    wait_fixed,
)

from codespace import shared
from codespace.client import ssh_config
from codespace.client.config import AgentProfile, WebConfig
from codespace.client.providers import PROVIDER_ERRORS, provider_client

KEY_DIR = Path.home() / ".ssh" / "codespace"
HTTP_TIMEOUT = 30.0
DASHBOARD_TIMEOUT = 3.0
CLONE_HTTP_TIMEOUT = 30 * 60.0
CREATE_POLL_INTERVAL = 2.0
CREATE_OPERATION_TIMEOUT = 30 * 60.0
CLONE_RETRY_INTERVAL = 2.0
CLONE_ATTEMPTS = 5
ProgressCallback = Callable[[str], None]
JsonValue = dict[str, Any] | list[Any] | str | int | float | bool | None


class ServiceError(RuntimeError):
    """Base error raised by client service orchestration."""


class _OperationPending(RuntimeError):
    """Internal retry signal for an agent create operation that is still busy."""


class _CloneNotReady(RuntimeError):
    """Internal retry signal for clone requests that failed transiently."""


class AgentListResult(BaseModel):
    """Result of listing one agent."""

    agent: AgentProfile
    online: bool
    codespaces: list[shared.Codespace] = Field(default_factory=list)
    error: str | None = None


class CreateCodespaceInput(BaseModel):
    """Input for service-level create orchestration."""

    model_config = ConfigDict(extra="forbid")

    repo: str
    provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER
    template: str = shared.DEFAULT_TEMPLATE
    instance: str = shared.DEFAULT_INSTANCE
    image: str


class DeleteCodespaceResult(BaseModel):
    """Result returned after deleting a codespace."""

    ok: bool = True
    workspace_removed: bool = False
    warning: str | None = None


class SshHttpTunnel:
    """Local SSH tunnel that exposes a remote agent HTTP endpoint on localhost."""

    def __init__(self, profile: AgentProfile) -> None:
        self.profile = profile
        self.local_url = _local_agent_url(profile.agent_url, _free_local_port())
        self._process = self._start()
        _wait_for_agent(self.local_url)

    def close(self) -> None:
        """Stop the SSH tunnel process if it is still running."""
        if self._process.poll() is None:
            self._process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self._process.wait(timeout=2)
        if self._process.poll() is None:
            self._process.kill()

    def is_running(self) -> bool:
        """Return whether the SSH tunnel process is still alive."""
        return self._process.poll() is None

    def _start(self) -> subprocess.Popen[bytes]:
        parsed = urlparse(self.profile.agent_url)
        if parsed.scheme not in {"http", "https"}:
            raise ServiceError(
                f"agent_url must be http(s) when ssh_proxy is enabled: {parsed.scheme}"
            )
        if parsed.hostname is None:
            raise ServiceError("agent_url must include a host when ssh_proxy is enabled")
        target_host = _agent_target_host(parsed.hostname)
        target_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        local_port = urlparse(self.local_url).port
        if local_port is None:
            raise ServiceError("failed to allocate local ssh proxy port")
        if self.profile.ssh_proxy_host is None:
            raise ServiceError("ssh_proxy_host is required when ssh_proxy is enabled")
        process = subprocess.Popen(  # noqa: S603
            [  # noqa: S607
                "ssh",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "ServerAliveInterval=30",
                "-o",
                "ServerAliveCountMax=2",
                "-N",
                "-L",
                f"127.0.0.1:{local_port}:{_ssh_forward_target_host(target_host)}:{target_port}",
                self.profile.ssh_proxy_host,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        time.sleep(0.2)
        if process.poll() is not None:
            _, stderr = process.communicate()
            message = stderr.decode(errors="replace").strip() or "ssh proxy failed to start"
            raise ServiceError(message)
        return process


def instance_alias(agent_id: str, template: str, instance: str) -> str:
    """Local SSH alias for a template instance."""
    return f"{agent_id}-{template}-{instance}"


def _free_local_port() -> int:
    """Return an available localhost TCP port for an SSH local forward."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _local_agent_url(agent_url: str, local_port: int) -> str:
    """Return a localhost URL preserving the configured agent URL path."""
    parsed = urlparse(agent_url)
    return urlunparse(parsed._replace(netloc=f"127.0.0.1:{local_port}"))


def _agent_target_host(hostname: str) -> str:
    """Map wildcard agent hosts to loopback for SSH local forwarding."""
    return "127.0.0.1" if hostname in {"0.0.0.0", "::"} else hostname  # noqa: S104


def _ssh_forward_target_host(hostname: str) -> str:
    """Render a host token that is valid inside an OpenSSH ``-L`` specification."""
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return hostname
    return f"[{hostname}]" if address.version == 6 else hostname


def _wait_for_agent(local_url: str) -> None:
    """Wait briefly until the forwarded local agent port accepts HTTP requests."""
    try:
        for attempt in Retrying(
            stop=stop_after_delay(3),
            wait=wait_fixed(0.1),
            retry=retry_if_exception_type(httpx.RequestError),
            reraise=True,
        ):
            with attempt:
                with httpx.Client(timeout=0.3) as client:
                    client.get(f"{local_url.rstrip('/')}/codespaces")
                return
    except httpx.RequestError as exc:
        raise ServiceError(f"ssh proxy started but agent is not reachable: {exc}") from exc


def _poll_retry(timeout_s: float, interval_s: float) -> Retrying:
    """Return a fixed-interval retry iterator for polling loops."""
    return Retrying(
        stop=stop_after_delay(timeout_s),
        wait=wait_fixed(interval_s),
        retry=retry_if_exception_type(_OperationPending),
        reraise=True,
    )


def _clone_retry() -> Retrying:
    """Return the retry policy used while waiting for agent-side clone readiness."""
    return Retrying(
        stop=stop_after_attempt(CLONE_ATTEMPTS),
        wait=wait_fixed(CLONE_RETRY_INTERVAL),
        retry=retry_if_exception_type(_CloneNotReady),
        reraise=True,
    )


def request(
    method: str, url: str, body: dict | None = None, *, timeout: float = HTTP_TIMEOUT
) -> tuple[int, JsonValue]:
    """Perform an HTTP request and return ``(status, parsed_json)``."""
    try:
        resp = httpx.request(method, url, json=body, timeout=timeout)
    except httpx.RequestError as exc:
        raise ServiceError(f"cannot reach agent: {exc}") from exc
    try:
        return resp.status_code, (resp.json() if resp.content else {})
    except ValueError:
        return resp.status_code, {"error": resp.text or resp.reason_phrase}


def agent_error(data: JsonValue, status: int) -> str:
    """Render an actionable error message from an agent HTTP response."""
    if not isinstance(data, dict):
        return f"agent returned HTTP {status}"
    if data.get("error"):
        return str(data["error"])
    detail = data.get("detail")
    if detail:
        return f"agent returned HTTP {status}: {_format_validation_detail(detail)}"
    return f"agent returned HTTP {status}"


def _format_validation_detail(detail: object) -> str:
    if isinstance(detail, list):
        parts: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(part) for part in item.get("loc", []))
                msg = item.get("msg", item.get("type", "validation error"))
                parts.append(f"{loc}: {msg}" if loc else str(msg))
            else:
                parts.append(str(item))
        return "; ".join(parts)
    return str(detail)


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
    if not pub_path.exists():
        result = subprocess.run(  # noqa: S603
            ["ssh-keygen", "-y", "-f", str(key_path)],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
        pub_path.write_text(result.stdout.strip() + "\n", encoding="utf-8")
    return pub_path.read_text(encoding="utf-8").strip()


def remove_login_key(alias: str) -> None:
    """Delete the local login keypair for ``alias``."""
    for path in (KEY_DIR / alias, KEY_DIR / f"{alias}.pub"):
        path.unlink(missing_ok=True)


def revoke_quietly(
    token: str,
    repo: str,
    cs_id: str,
    *,
    provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER,
) -> None:
    """Best-effort deploy-key revocation used during create rollback."""
    with contextlib.suppress(*PROVIDER_ERRORS):
        provider_client(provider).delete_deploy_key(token, repo, cs_id)


class CodespaceService:
    """Client-side operations for the local Web GUI."""

    def __init__(self, config: WebConfig) -> None:
        self.config = config
        self._tunnels: dict[str, SshHttpTunnel] = {}
        self._tunnel_lock = Lock()

    def close(self) -> None:
        """Close any SSH HTTP proxy tunnels opened by this service."""
        with self._tunnel_lock:
            tunnels = list(self._tunnels.values())
            self._tunnels.clear()
        for tunnel in tunnels:
            tunnel.close()

    def agent(self, agent_id: str) -> AgentProfile:
        """Return an agent profile by id."""
        if agent_id not in self.config.agents:
            raise ServiceError(f"unknown agent: {agent_id}")
        return self.config.agents[agent_id]

    def list_agent_codespaces(self, agent_id: str) -> AgentListResult:
        """List codespaces for one configured agent, converting errors to offline results."""
        profile = self.agent(agent_id)
        try:
            status, data = self.request_agent(
                profile, "GET", "/codespaces", timeout=DASHBOARD_TIMEOUT
            )
            if status != 200:
                return AgentListResult(
                    agent=profile,
                    online=False,
                    error=agent_error(data, status),
                )
            if not isinstance(data, list):
                return AgentListResult(
                    agent=profile,
                    online=False,
                    error="agent returned non-list response",
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
        max_workers = max(1, len(self.config.agents))
        results: dict[str, AgentListResult] = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.list_agent_codespaces, agent_id): agent_id
                for agent_id in self.config.agents
            }
            for future in as_completed(futures):
                agent_id = futures[future]
                results[agent_id] = future.result()
        return [results[agent_id] for agent_id in self.config.agents]

    def request_agent(
        self,
        profile: AgentProfile,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        timeout: float = HTTP_TIMEOUT,
    ) -> tuple[int, JsonValue]:
        """Request an agent directly or through a client-side SSH HTTP proxy."""
        base_url = self._agent_base_url(profile)
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
        return request(method, url, body, timeout=timeout)

    def _agent_base_url(self, profile: AgentProfile) -> str:
        if not profile.ssh_proxy:
            return profile.agent_url
        with self._tunnel_lock:
            tunnel = self._tunnels.get(profile.id)
            if tunnel is None or not tunnel.is_running():
                tunnel = SshHttpTunnel(profile)
                self._tunnels[profile.id] = tunnel
            return tunnel.local_url

    def wait_create_operation(
        self,
        profile: AgentProfile,
        operation_id: str,
        *,
        progress: ProgressCallback | None = None,
    ) -> shared.Codespace:
        """Poll an asynchronous agent create operation until completion."""
        try:
            for attempt in _poll_retry(CREATE_OPERATION_TIMEOUT, CREATE_POLL_INTERVAL):
                with attempt:
                    status_code, data = self.request_agent(
                        profile,
                        "GET",
                        f"/operations/{operation_id}",
                    )
                    if status_code != 200:
                        raise ServiceError(agent_error(data, status_code))
                    if not isinstance(data, dict):
                        raise ServiceError("agent returned invalid operation response")
                    operation = shared.CreateOperation.model_validate(data)
                    if progress is not None:
                        progress(f"agent: {operation.stage}")
                    match operation.status:
                        case "queued" | "running":
                            raise _OperationPending
                        case "succeeded":
                            if operation.codespace is None:
                                raise ServiceError(
                                    "agent completed create without returning a codespace"
                                )
                            return operation.codespace
                        case "failed":
                            raise ServiceError(
                                operation.error or "agent failed to provision codespace"
                            )
        except _OperationPending as exc:
            raise ServiceError(
                f"agent create operation timed out after {CREATE_OPERATION_TIMEOUT:.0f}s"
            ) from exc
        raise ServiceError(
            f"agent create operation timed out after {CREATE_OPERATION_TIMEOUT:.0f}s"
        )

    def clone_remote_repo(self, profile: AgentProfile, codespace_id: str) -> None:
        """Ask the agent to clone the main repo after deploy keys are registered."""
        try:
            for attempt in _clone_retry():
                with attempt:
                    status, data = self.request_agent(
                        profile,
                        "POST",
                        f"/codespaces/{codespace_id}/clone",
                        timeout=CLONE_HTTP_TIMEOUT,
                    )
                    if status == 200:
                        return
                    raise _CloneNotReady(agent_error(data, status))
        except _CloneNotReady as exc:
            raise ServiceError(str(exc) or "agent failed to clone repo") from exc

    def create_codespace(
        self,
        agent_id: str,
        req: CreateCodespaceInput,
        *,
        token: str,
        progress: ProgressCallback | None = None,
    ) -> shared.Codespace:
        """Create a codespace on one agent and register local provider state."""
        profile = self.agent(agent_id)
        registered = False
        cs: shared.Codespace | None = None
        try:
            provider = req.provider
            if progress is not None:
                progress("preparing login key")
            alias = instance_alias(agent_id, req.template, req.instance)
            login_pubkey = ensure_login_key(alias)
            payload = shared.CreateRequest(
                repo=req.repo,
                provider=provider,
                template=req.template,
                instance=req.instance,
                login_pubkey=login_pubkey,
                image=req.image,
            )
            if progress is not None:
                progress("requesting agent creation")
            status, data = self.request_agent(profile, "POST", "/codespaces", payload.model_dump())
            if status != 202:
                raise ServiceError(agent_error(data, status))
            if not isinstance(data, dict):
                raise ServiceError("agent returned invalid create response")

            operation = shared.CreateOperation.model_validate(data)
            cs = self.wait_create_operation(profile, operation.id, progress=progress)
            if not cs.deploy_public_key:
                raise ServiceError("agent did not return a deploy public key")

            if progress is not None:
                progress(f"registering deploy key: {cs.repo}")
            provider_client(cs.provider).register_deploy_key(
                token,
                cs.repo,
                cs.id,
                cs.deploy_public_key,
            )
            registered = True

            if progress is not None:
                progress("cloning repo into workspace")
            self.clone_remote_repo(profile, cs.id)

            if progress is not None:
                progress("writing ssh config")
            ssh_config.upsert(
                alias,
                profile.ssh_host,
                cs.port,
                cs.user,
                cs.id,
                agent_id=agent_id,
                repo=cs.repo,
                provider=cs.provider,
                ssh_options=profile.ssh_options,
            )
            return cs
        except Exception:
            if cs is not None:
                if registered:
                    revoke_quietly(token, cs.repo, cs.id, provider=cs.provider)
                with contextlib.suppress(Exception):
                    self.delete_remote(profile, cs.id)
            remove_login_key(instance_alias(agent_id, req.template, req.instance))
            raise

    def delete_codespace(
        self,
        agent_id: str,
        codespace_id: str,
        *,
        token: str | None,
        repo: str | None = None,
        provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER,
        purge: bool = False,
    ) -> DeleteCodespaceResult:
        """Delete a remote codespace and clean local/provider state."""
        profile = self.agent(agent_id)
        entry = ssh_config.find_entry(codespace_id=codespace_id, agent_id=agent_id)
        alias = entry.alias if entry else None
        revoke_repo = entry.repo if entry else None
        warning = None
        if not revoke_repo and repo:
            revoke_repo = repo
            warning = "local alias not found; only main repo deploy key was revoked"
        resp = self.delete_remote(profile, codespace_id, purge=purge)
        key_provider = entry.provider if entry else provider
        client = provider_client(key_provider)
        if token:
            if not revoke_repo:
                warning = (
                    f"{client.display_name} token is available, but repo metadata is missing; "
                    "skipped deploy key revocation"
                )
            else:
                try:
                    client.delete_deploy_key(token, revoke_repo, codespace_id)
                except PROVIDER_ERRORS as exc:
                    warning = (
                        f"{client.display_name} deploy key revocation failed for "
                        f"{revoke_repo}: {exc}; deleted codespace anyway"
                    )
        elif revoke_repo:
            warning = f"{client.display_name} token is not available; skipped deploy key revocation"
        if alias:
            ssh_config.remove(alias)
            remove_login_key(alias)
        return DeleteCodespaceResult(
            ok=resp.ok, workspace_removed=resp.workspace_removed, warning=warning
        )

    def delete_remote(
        self, profile: AgentProfile, cs_id: str, *, purge: bool = False
    ) -> shared.DeleteResponse:
        """Delete a codespace container on an agent through the configured transport."""
        path = f"/codespaces/{cs_id}"
        if purge:
            path += "?purge=true"
        status, data = self.request_agent(profile, "DELETE", path)
        if status != 200:
            raise ServiceError(agent_error(data, status))
        if not isinstance(data, dict):
            raise ServiceError("agent returned invalid delete response")
        return shared.DeleteResponse.model_validate(data)
