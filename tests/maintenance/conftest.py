"""Connection fixtures for maintenance commands."""

from __future__ import annotations

from collections.abc import Callable, Collection
from pathlib import Path
from types import ModuleType
from typing import Protocol

import pytest

from codespace.runtime.transport import SSHRoute


class Client(Protocol):
    def close(self) -> None: ...


type TransportInstaller = Callable[[ModuleType, Callable[[str], Client]], dict[str, object]]


@pytest.fixture
def install_transport(monkeypatch: pytest.MonkeyPatch) -> TransportInstaller:
    def install(module: ModuleType, create_client: Callable[[str], Client]) -> dict[str, object]:
        options: dict[str, object] = {}

        class FakeTransport:
            def __init__(self, hosts: Collection[str], *, client_timeout: float) -> None:
                options.update(hosts=list(hosts), client_timeout=client_timeout)
                self.clients: dict[str, Client] = {}

            def client(self, host: str) -> Client:
                if host not in self.clients:
                    self.clients[host] = create_client(host)
                return self.clients[host]

            def ssh_route(self, host: str) -> SSHRoute:
                self.client(host)
                return SSHRoute(host, Path(f"/tmp/control-{host}.sock"))

            def close(self) -> None:
                for client in self.clients.values():
                    client.close()

        monkeypatch.setattr(module, "PodmanTransport", FakeTransport)
        return options

    return install
