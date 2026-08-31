"""Tests for the out-of-band Podman secret sync tool."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console
from typer.testing import CliRunner

from controller.config import Config
from controller.tools import sync_secrets


@pytest.fixture
def config() -> Config:
    return Config.model_validate(
        {
            "workspaces": {
                "defaults": {"image": "image", "container": {"network_mode": "host"}},
                "items": {
                    "devspace": {
                        "repo": "github:owner/repo",
                        "host": [{"name": "home"}, {"name": "office"}],
                    }
                },
            },
            "hosts": {"home": {}, "office": {}},
            "secrets": {
                "supabase_service_key": "svc-value",
                "supabase_anon": "anon-value",
            },
        }
    )


class FakeSecrets:
    def __init__(self, existing: set[str]) -> None:
        self.existing = set(existing)
        self.created: list[tuple[str, bytes]] = []
        self.removed: list[str] = []

    def exists(self, key: str) -> bool:
        return key in self.existing

    def remove(self, secret_id: str, all: bool | None = None) -> None:
        self.removed.append(secret_id)
        self.existing.discard(secret_id)

    def create(self, name: str, data: bytes, **_: object) -> None:
        self.created.append((name, data))
        self.existing.add(name)


class FakeClient:
    def __init__(self, secrets: FakeSecrets) -> None:
        self.secrets = secrets


class FakeTransport:
    def __init__(self, clients: dict[str, FakeClient]) -> None:
        self.clients = clients
        self.closed = False

    def client(self, host: str) -> FakeClient:
        return self.clients[host]

    def close(self) -> None:
        self.closed = True


def _run(
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    transport: FakeTransport,
    arguments: list[str],
) -> str:
    output = StringIO()
    monkeypatch.setattr(sync_secrets, "console", Console(file=output, width=120))
    monkeypatch.setattr(sync_secrets, "load_config", lambda _path: config)
    monkeypatch.setattr(sync_secrets, "PodmanTransport", lambda _hosts: transport)
    result = CliRunner().invoke(sync_secrets.app, arguments)
    assert result.exit_code == 0
    return output.getvalue()


def test_dry_run_reports_plan_for_every_host_without_writing(
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
) -> None:
    clients = {
        "home": FakeClient(FakeSecrets(set())),
        "office": FakeClient(FakeSecrets({"supabase_service_key"})),
    }
    transport = FakeTransport(clients)

    rendered = _run(monkeypatch, config, transport, [])

    # Every host gets every declared secret: 2 hosts x 2 secrets.
    assert "Dry run: 4 secret(s)" in rendered
    assert "create" in rendered
    assert "replace" in rendered
    assert clients["home"].secrets.created == []
    assert clients["office"].secrets.created == []
    assert transport.closed is True


def test_no_dry_run_creates_all_secrets_on_all_hosts(
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
) -> None:
    home = FakeClient(FakeSecrets(set()))
    office = FakeClient(FakeSecrets({"supabase_service_key"}))
    transport = FakeTransport({"home": home, "office": office})

    rendered = _run(monkeypatch, config, transport, ["--no-dry-run"])

    assert "Applied 4 secret(s)." in rendered
    # home had neither secret: two fresh creations, no removals.
    assert dict(home.secrets.created) == {
        "supabase_service_key": b"svc-value",
        "supabase_anon": b"anon-value",
    }
    assert home.secrets.removed == []
    # office already had the service key: it is removed then recreated.
    assert office.secrets.removed == ["supabase_service_key"]
    assert dict(office.secrets.created) == {
        "supabase_service_key": b"svc-value",
        "supabase_anon": b"anon-value",
    }


def test_no_secrets_declared_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config.model_validate(
        {
            "workspaces": {
                "defaults": {"image": "image", "container": {"network_mode": "host"}},
                "items": {"devspace": {"repo": "github:owner/repo", "host": [{"name": "home"}]}},
            },
            "hosts": {"home": {}},
        }
    )
    output = StringIO()
    monkeypatch.setattr(sync_secrets, "console", Console(file=output, width=120))
    monkeypatch.setattr(sync_secrets, "load_config", lambda _path: config)

    def _fail(_hosts: object) -> None:
        raise AssertionError("transport must not be created when no secrets are declared")

    monkeypatch.setattr(sync_secrets, "PodmanTransport", _fail)

    result = CliRunner().invoke(sync_secrets.app, [])

    assert result.exit_code == 0
    assert "nothing to sync" in output.getvalue()
