"""Composition root for the single-process local control plane."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock
from typing import Literal

from codespace.config import Config
from codespace.errors import ResourceConflict
from codespace.operations import describe_error
from codespace.runtime.transport import PodmanTransport, TransportError
from codespace.services.lifecycle import ServiceManager
from codespace.services.models import Service
from codespace.workspaces.lifecycle import WorkspaceManager
from codespace.workspaces.models import GitProvider, Workspace


@dataclass(frozen=True, slots=True)
class HostInventory:
    host: str
    workspaces: list[Workspace]
    services: list[Service]


@dataclass(frozen=True, slots=True)
class HostFailure:
    host: str
    status: Literal["offline", "error"]
    error: str


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
            raise ResourceConflict(f"{provider} token is not set")
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
        self.transport = transport or PodmanTransport(config.hosts)
        self.tokens = TokenStore(config.seed_tokens())
        self.workspaces = WorkspaceManager(config, self.transport, self.tokens.get)
        self.services = ServiceManager(config, self.transport)

    def close(self) -> None:
        self.transport.close()

    def inventory(self) -> dict[str, HostInventory | HostFailure]:
        with ThreadPoolExecutor(max_workers=len(self.config.hosts)) as executor:
            return dict(
                zip(
                    self.config.hosts,
                    executor.map(self._host_inventory, self.config.hosts),
                    strict=True,
                )
            )

    def _host_inventory(self, host_name: str) -> HostInventory | HostFailure:
        try:
            workspaces = self.workspaces.inventory(host_name)
            services = self.services.inventory(host_name)
            return HostInventory(
                host=host_name,
                workspaces=workspaces,
                services=services,
            )
        except Exception as exc:
            return HostFailure(
                host=host_name,
                status="offline" if isinstance(exc, TransportError) else "error",
                error=describe_error(exc),
            )
