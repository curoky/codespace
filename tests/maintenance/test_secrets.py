"""Tests for dry-run-first secret synchronization."""

from io import StringIO

import pytest
from rich.console import Console

from codespace.config import Config
from codespace.maintenance import secrets


class FakeSecrets:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def exists(self, name: str) -> bool:
        return name in self.values

    def remove(self, name: str) -> None:
        self.values.pop(name)

    def create(self, name: str, value: bytes) -> None:
        self.values[name] = value


class FakeTransport:
    def __init__(self) -> None:
        self.secrets = FakeSecrets()
        self.closed = False

    def client(self, _host: str) -> object:
        return type("Client", (), {"secrets": self.secrets})()

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
    assert transport.secrets.values == ({"api_token": b"value"} if apply else {})
    assert ("Applied" if apply else "Dry run") in stream.getvalue()
