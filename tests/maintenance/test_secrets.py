"""Tests for dry-run-first secret synchronization."""

from __future__ import annotations

from io import StringIO
from threading import Barrier

import pytest
from rich.console import Console

from codespace.config import Config
from codespace.maintenance import secrets

from .conftest import TransportInstaller


class FakeSecrets:
    def __init__(self, values: dict[str, bytes] | None = None) -> None:
        self.values = values or {}
        self.inspected: list[str] = []
        self.writes: list[tuple[str, str]] = []

    def exists(self, name: str) -> bool:
        self.inspected.append(name)
        return name in self.values

    def remove(self, name: str) -> None:
        self.writes.append(("remove", name))
        self.values.pop(name)

    def create(self, name: str, value: bytes) -> None:
        self.writes.append(("create", name))
        if name in self.values:
            raise RuntimeError("secret already exists")
        self.values[name] = value


class FakeClient:
    def __init__(self, secrets_store: FakeSecrets) -> None:
        self.secrets = secrets_store
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("apply", [False, True])
def test_sync_only_writes_with_apply(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    install_transport: TransportInstaller,
    apply: bool,
) -> None:
    configured = Config.model_validate(
        {**config.model_dump(), "secrets": {"api_token": "value", "new": "created"}}
    )
    stores = {
        "home": FakeSecrets({"api_token": b"old"}),
        "office": FakeSecrets(),
    }
    clients: list[FakeClient] = []
    stream = StringIO()

    def create_client(host: str) -> FakeClient:
        client = FakeClient(stores[host])
        clients.append(client)
        return client

    monkeypatch.setattr(secrets, "load_config", lambda _path: configured)
    options = install_transport(secrets, create_client)

    secrets.sync(apply=apply, console=Console(file=stream, width=120))

    assert all(client.closed for client in clients)
    assert options == {"hosts": ["home", "office"], "client_timeout": secrets._CLIENT_TIMEOUT}
    assert stores["home"].values == (
        {"api_token": b"value", "new": b"created"} if apply else {"api_token": b"old"}
    )
    assert stores["office"].values == ({"api_token": b"value", "new": b"created"} if apply else {})
    assert ("Applied" if apply else "Dry run") in stream.getvalue()
    assert all(store.inspected == ["api_token", "new"] for store in stores.values())
    if apply:
        assert "Applied 4 secret(s)." in stream.getvalue()


def test_sync_checks_all_hosts_and_prints_plan_before_writing(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    install_transport: TransportInstaller,
) -> None:
    configured = Config.model_validate(
        {**config.model_dump(), "secrets": {"replace": "updated", "create": "new"}}
    )
    stores = {
        "home": FakeSecrets({"replace": b"old"}),
        "office": FakeSecrets(),
    }
    stream = StringIO()
    create = stores["home"].create

    def create_after_plan(name: str, value: bytes) -> None:
        assert all(store.inspected == ["create", "replace"] for store in stores.values())
        assert "home" in stream.getvalue()
        assert "office" in stream.getvalue()
        assert "replace" in stream.getvalue()
        assert "Applied" not in stream.getvalue()
        create(name, value)

    def create_client(host: str) -> FakeClient:
        return FakeClient(stores[host])

    monkeypatch.setattr(secrets, "load_config", lambda _path: configured)
    install_transport(secrets, create_client)
    monkeypatch.setattr(stores["home"], "create", create_after_plan)

    secrets.sync(apply=True, console=Console(file=stream, width=120))

    assert stores["home"].values == {"replace": b"updated", "create": b"new"}
    assert stores["home"].writes == [
        ("create", "create"),
        ("remove", "replace"),
        ("create", "replace"),
    ]


@pytest.mark.parametrize("failure", ["connect", "inventory"])
def test_sync_host_failure_closes_clients_without_writing(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    install_transport: TransportInstaller,
    failure: str,
) -> None:
    configured = Config.model_validate({**config.model_dump(), "secrets": {"api_token": "value"}})
    stores = {"home": FakeSecrets({"api_token": b"old"}), "office": FakeSecrets()}
    clients: list[FakeClient] = []
    stream = StringIO()

    def fail_inventory(_name: str) -> bool:
        raise RuntimeError("scan unavailable")

    def create_client(host: str) -> FakeClient:
        if host == "office" and failure == "connect":
            raise RuntimeError("scan unavailable")
        client = FakeClient(stores[host])
        clients.append(client)
        return client

    monkeypatch.setattr(secrets, "load_config", lambda _path: configured)
    install_transport(secrets, create_client)
    if failure == "inventory":
        monkeypatch.setattr(stores["office"], "exists", fail_inventory)

    with pytest.raises(RuntimeError, match="scan unavailable"):
        secrets.sync(apply=True, console=Console(file=stream, width=120))

    assert stream.getvalue() == ""
    assert stores["home"].values == {"api_token": b"old"}
    assert all(not store.writes for store in stores.values())
    assert all(client.closed for client in clients)


def test_sync_scans_and_applies_hosts_concurrently(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    install_transport: TransportInstaller,
) -> None:
    configured = Config.model_validate({**config.model_dump(), "secrets": {"token": "value"}})
    clients = {host: FakeClient(FakeSecrets()) for host in configured.hosts}
    scanned = Barrier(len(clients))
    applied = Barrier(len(clients))

    def exists(self: FakeSecrets, name: str) -> bool:
        self.inspected.append(name)
        scanned.wait(timeout=5)
        return False

    def create(self: FakeSecrets, name: str, value: bytes) -> None:
        assert all(client.secrets.inspected == ["token"] for client in clients.values())
        applied.wait(timeout=5)
        self.values[name] = value

    monkeypatch.setattr(secrets, "load_config", lambda _path: configured)
    monkeypatch.setattr(FakeSecrets, "exists", exists)
    monkeypatch.setattr(FakeSecrets, "create", create)
    install_transport(secrets, clients.__getitem__)

    secrets.sync(apply=True, console=Console(file=StringIO()))

    assert all(client.secrets.values == {"token": b"value"} for client in clients.values())
    assert all(client.closed for client in clients.values())
