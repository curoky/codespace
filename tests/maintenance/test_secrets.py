"""Tests for dry-run-first secret synchronization."""

from io import StringIO
from types import SimpleNamespace

import pytest
from rich.console import Console

from codespace.config import Config
from codespace.maintenance import secrets


class FakeSecrets:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}
        self.writes: list[tuple[str, str]] = []

    def exists(self, name: str) -> bool:
        return name in self.values

    def remove(self, name: str) -> None:
        self.writes.append(("remove", name))
        self.values.pop(name)

    def create(self, name: str, value: bytes) -> None:
        self.writes.append(("create", name))
        if name in self.values:
            raise RuntimeError("secret already exists")
        self.values[name] = value


class FakeTransport:
    def __init__(self) -> None:
        self.hosts = {host: FakeSecrets() for host in ("home", "office")}
        self.closed = False

    def client(self, host: str) -> SimpleNamespace:
        return SimpleNamespace(secrets=self.hosts[host])

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize("apply", [False, True])
def test_sync_only_writes_with_apply(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    apply: bool,
) -> None:
    configured = Config.model_validate({**config.model_dump(), "secrets": {"api_token": "value"}})
    transport = FakeTransport()
    stream = StringIO()
    monkeypatch.setattr(secrets, "load_config", lambda _path: configured)
    monkeypatch.setattr(secrets, "PodmanTransport", lambda _hosts: transport)

    secrets.sync(apply=apply, console=Console(file=stream, width=120))

    assert transport.closed is True
    assert all(
        host.values == ({"api_token": b"value"} if apply else {})
        for host in transport.hosts.values()
    )
    assert ("Applied" if apply else "Dry run") in stream.getvalue()
    if apply:
        assert "Applied 2 secret(s)." in stream.getvalue()


def test_failed_host_is_not_retried_during_apply(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = Config.model_validate({**config.model_dump(), "secrets": {"api_token": "value"}})
    transport = FakeTransport()
    calls: list[str] = []
    stream = StringIO()

    def client(host: str) -> SimpleNamespace:
        calls.append(host)
        if host == "office":
            raise RuntimeError("scan unavailable")
        return SimpleNamespace(secrets=transport.hosts[host])

    monkeypatch.setattr(transport, "client", client)
    monkeypatch.setattr(secrets, "load_config", lambda _path: configured)
    monkeypatch.setattr(secrets, "PodmanTransport", lambda _hosts: transport)

    secrets.sync(apply=True, console=Console(file=stream, width=120))

    assert calls.count("office") == 1
    assert transport.hosts["office"].writes == []
    assert transport.hosts["home"].values == {"api_token": b"value"}
    assert "scan unavailable" in stream.getvalue()
    assert "Applied 1 secret(s)." in stream.getvalue()


@pytest.mark.parametrize("action", ["create", "replace"])
def test_changed_plan_precondition_fails_without_mutation(
    action: secrets.Action,
) -> None:
    transport = FakeTransport()
    store = transport.hosts["home"]
    if action == "create":
        store.values["api_token"] = b"created elsewhere"
    before = dict(store.values)
    plan = [secrets.SecretChange("home", "api_token", action, "sensitive-value")]

    applied, errors = secrets._apply(transport, plan)  # type: ignore[arg-type]

    assert applied == 0
    assert len(errors) == 1
    assert "state changed since planning" in errors[0]
    assert store.values == before
    assert store.writes == []
    assert "sensitive-value" not in repr(plan)


def test_apply_uses_planned_value_and_continues_after_item_failure() -> None:
    transport = FakeTransport()
    store = transport.hosts["home"]
    store.values["replace"] = b"old"
    plan = [
        secrets.SecretChange("home", "missing", "replace", "not-applied"),
        secrets.SecretChange("home", "replace", "replace", "planned"),
        secrets.SecretChange("home", "new", "create", "new-value"),
    ]

    applied, errors = secrets._apply(transport, plan)  # type: ignore[arg-type]

    assert applied == 2
    assert len(errors) == 1
    assert store.values == {"replace": b"planned", "new": b"new-value"}
    assert store.writes == [("remove", "replace"), ("create", "replace"), ("create", "new")]
    assert transport.hosts["office"].writes == []
