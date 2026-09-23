"""Tests for dry-run-first secret synchronization."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console

from codespace.config import Config
from codespace.maintenance import secrets


class FakeSecrets:
    def __init__(self, values: dict[str, bytes] | None = None) -> None:
        self.values = values or {}
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


class FakeClient:
    def __init__(self, secrets_store: FakeSecrets) -> None:
        self.secrets = secrets_store
        self.closed = False

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True


@pytest.mark.parametrize("apply", [False, True])
def test_sync_only_writes_with_apply(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
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
    options: list[dict[str, object]] = []
    stream = StringIO()

    def create_client(**kwargs: object) -> FakeClient:
        host = str(kwargs["base_url"]).removeprefix("http+ssh://").partition("/")[0]
        client = FakeClient(stores[host])
        clients.append(client)
        options.append(kwargs)
        return client

    monkeypatch.setattr(secrets, "load_config", lambda _path: configured)
    monkeypatch.setattr(secrets, "PodmanClient", create_client)

    secrets.sync(apply=apply, console=Console(file=stream, width=120))

    assert all(client.closed for client in clients)
    assert {option["timeout"] for option in options} == {secrets._CLIENT_TIMEOUT}
    assert stores["home"].values == (
        {"api_token": b"value", "new": b"created"} if apply else {"api_token": b"old"}
    )
    assert stores["office"].values == ({"api_token": b"value", "new": b"created"} if apply else {})
    assert ("Applied" if apply else "Dry run") in stream.getvalue()
    if apply:
        assert "Applied 4 secret(s)." in stream.getvalue()


def test_sync_host_reports_sorted_actions_and_replaces_existing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FakeSecrets({"replace": b"old"})
    client = FakeClient(store)
    options: dict[str, object] = {}

    def create_client(**kwargs: object) -> FakeClient:
        options.update(kwargs)
        return client

    monkeypatch.setattr(secrets, "PodmanClient", create_client)

    assert secrets._sync_host(
        "home",
        configured={"replace": "updated", "create": "new"},
        apply=True,
    ) == [("create", "create"), ("replace", "replace")]
    assert options == {
        "base_url": "http+ssh://home/run/podman/podman.sock",
        "timeout": secrets._CLIENT_TIMEOUT,
    }
    assert store.values == {"replace": b"updated", "create": b"new"}
    assert store.writes == [
        ("create", "create"),
        ("remove", "replace"),
        ("create", "replace"),
    ]
    assert client.closed is True


def test_sync_fails_on_host_error(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    configured = Config.model_validate({**config.model_dump(), "secrets": {"api_token": "value"}})
    stream = StringIO()

    def sync_host(
        host: str,
        *,
        configured: dict[str, str],
        apply: bool,
    ) -> list[tuple[str, secrets.Action]]:
        assert configured == {"api_token": "value"}
        assert apply is True
        if host == "office":
            raise RuntimeError("scan unavailable")
        return [("api_token", "create")]

    monkeypatch.setattr(secrets, "load_config", lambda _path: configured)
    monkeypatch.setattr(secrets, "_sync_host", sync_host)

    with pytest.raises(RuntimeError, match="scan unavailable"):
        secrets.sync(apply=True, console=Console(file=stream, width=120))

    assert stream.getvalue() == ""
