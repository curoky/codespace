"""Composition root for the single-process local control plane."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from codespace.config import Config
from codespace.operations import describe_error
from codespace.runtime.transport import PodmanTransport
from codespace.services.lifecycle import ServiceManager
from codespace.web import dashboard as dashboard_state
from codespace.web.models import DashboardResponse, HostStatus
from codespace.workspaces import ssh
from codespace.workspaces.lifecycle import WorkspaceManager
from codespace.workspaces.models import GitProvider


class TokenStore:
    """Process-local provider tokens that never cross a response boundary."""

    def __init__(self, values: dict[GitProvider, str] | None = None) -> None:
        self._values = dict(values or {})
        self._lock = Lock()

    def set(self, provider: GitProvider, token: str) -> None:
        with self._lock:
            self._values[provider] = token

    def get(self, provider: GitProvider) -> str:
        with self._lock:
            token = self._values.get(provider)
        if token is None:
            raise RuntimeError(f"{provider} token is not set")
        return token

    def status(self) -> dict[GitProvider, bool]:
        with self._lock:
            return {
                "github": "github" in self._values,
                "gitlab": "gitlab" in self._values,
            }


class ControlPlane:
    """Own shared connections and compose the two independent managers."""

    def __init__(
        self,
        config: Config,
        *,
        transport: PodmanTransport | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or PodmanTransport(
            {host: options.endpoint() for host, options in config.hosts.items()}
        )
        self.tokens = TokenStore(config.seed_tokens())
        self.workspaces = WorkspaceManager(config, self.transport, self.tokens.get)
        self.services = ServiceManager(config, self.transport)
        ssh.initialize(list(config.hosts))

    def close(self) -> None:
        self.transport.close()

    def dashboard(self) -> DashboardResponse:
        with ThreadPoolExecutor(max_workers=len(self.config.hosts)) as executor:
            inventories = dict(
                zip(
                    self.config.hosts,
                    executor.map(self._host_inventory, self.config.hosts),
                    strict=True,
                )
            )
        return dashboard_state.build(
            self.config,
            inventories,
            operations=[*self.workspaces.operations.list(), *self.services.operations.list()],
            tokens=self.tokens.status(),
        )

    def _host_inventory(self, host_name: str) -> dashboard_state.HostInventory:
        try:
            route = self.transport.ssh_route(host_name)
            workspaces = self.workspaces.inventory(host_name)
            ssh.write_host(host_name, workspaces, route)
            services = self.services.inventory(host_name)
            return dashboard_state.HostInventory(
                status=HostStatus(
                    id=host_name,
                    status="online",
                    workspace_count=len(workspaces),
                ),
                workspaces=workspaces,
                services=services,
            )
        except Exception as exc:
            return dashboard_state.HostInventory(
                status=HostStatus(
                    id=host_name,
                    status="offline",
                    error=describe_error(exc),
                ),
                workspaces=[],
                services=[],
            )
