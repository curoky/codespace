"""Tests for resource-volume synchronization over reusable SSH connections."""

from __future__ import annotations

from collections.abc import Iterator
from io import StringIO
from threading import Barrier

import pytest
from podman.errors import APIError, PodmanError
from rich.console import Console

from codespace.config import Config
from codespace.maintenance import resources

from .conftest import TransportInstaller

_RESOURCE_IMAGE = "ghcr.io/curoky/codespace:workspace-resource"
_DIGEST = "sha256:0123456789abcdef"
_UPDATED_DIGEST = "sha256:fedcba9876543210"


class FakeVolumes:
    def __init__(self, existing: bool) -> None:
        self.existing = existing
        self.created = False
        self.inspections = 0

    def exists(self, _name: str) -> bool:
        self.inspections += 1
        return self.existing

    def create(self, _name: str) -> None:
        self.existing = True
        self.created = True


class FakeImages:
    def __init__(self, events: list[dict[str, str]] | None = None) -> None:
        self.events = events or [{"status": "pulled"}]
        self.pulls = 0
        self.requested: list[tuple[str, str]] = []

    def get(self, image: str) -> FakeImage:
        self.requested.append(("get", image))
        return FakeImage()

    def pull(self, image: str, **_kwargs: object) -> Iterator[dict[str, str]]:
        self.pulls += 1
        self.requested.append(("pull", image))
        return iter(self.events)


class FakeImage:
    def __init__(self) -> None:
        self.attrs = {"Digest": _DIGEST}


class FakeClient:
    def __init__(
        self,
        *,
        volume_exists: bool,
        pull_events: list[dict[str, str]] | None = None,
    ) -> None:
        self.volumes = FakeVolumes(volume_exists)
        self.images = FakeImages(pull_events)
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _install_client(
    monkeypatch: pytest.MonkeyPatch,
    install_transport: TransportInstaller,
    client: FakeClient,
) -> dict[str, object]:
    configured = Config.model_validate(
        {
            "hosts": {"home": {}},
            "project_defaults": {
                "resource_image": _RESOURCE_IMAGE,
                "container": {"image": "ghcr.io/curoky/codespace:workspace-debian13"},
            },
        }
    )
    monkeypatch.setattr(resources, "load_config", lambda _path: configured)
    return install_transport(resources, lambda _host: client)


def test_sync_host_uses_transport(
    monkeypatch: pytest.MonkeyPatch, install_transport: TransportInstaller
) -> None:
    client = FakeClient(volume_exists=True)
    options = _install_client(monkeypatch, install_transport, client)
    scripts: list[str] = []

    def run_helper(
        _client: FakeClient,
        resource_image: str,
        script: str,
        *,
        read_only: bool,
    ) -> tuple[int, str]:
        assert resource_image == _RESOURCE_IMAGE
        scripts.append(script)
        return 0, ""

    monkeypatch.setattr(resources, "_run_helper", run_helper)

    resources.sync(apply=False)
    assert options == {
        "hosts": ["home"],
        "client_timeout": resources._CLIENT_TIMEOUT,
    }
    assert scripts == ["grep -Fqx -- sha256:0123456789abcdef /dst/.codespace-resource-digest"]
    assert client.images.requested == [("get", _RESOURCE_IMAGE)]
    assert client.images.pulls == 0
    assert client.closed is True


def test_sync_host_pulls_before_comparing_digest(
    monkeypatch: pytest.MonkeyPatch, install_transport: TransportInstaller
) -> None:
    client = FakeClient(volume_exists=True)
    _install_client(monkeypatch, install_transport, client)
    pulled = False
    scripts: list[str] = []

    def pull(_image: str, **_kwargs: object) -> Iterator[dict[str, str]]:
        def events() -> Iterator[dict[str, str]]:
            nonlocal pulled
            client.images.pulls += 1
            pulled = True
            yield {"status": "pulled"}

        return events()

    def image_digest(_client: FakeClient, resource_image: str) -> str:
        assert resource_image == _RESOURCE_IMAGE
        return _UPDATED_DIGEST if pulled else _DIGEST

    def run_helper(
        _client: FakeClient,
        resource_image: str,
        script: str,
        *,
        read_only: bool,
    ) -> tuple[int, str]:
        assert resource_image == _RESOURCE_IMAGE
        scripts.append(script)
        if read_only:
            return (0, "") if _DIGEST in script else (1, "")
        return 0, ""

    monkeypatch.setattr(client.images, "pull", pull)
    monkeypatch.setattr(resources, "_image_digest", image_digest)
    monkeypatch.setattr(resources, "_run_helper", run_helper)

    resources.sync(apply=True)
    assert client.images.pulls == 1
    assert _DIGEST in scripts[0]
    assert _UPDATED_DIGEST in scripts[1]
    assert scripts[-1].endswith(
        f"printf '%s\\n' {_UPDATED_DIGEST} > /dst/.codespace-resource-digest"
    )


def test_sync_host_pulls_and_fills_existing_volume(
    monkeypatch: pytest.MonkeyPatch, install_transport: TransportInstaller
) -> None:
    client = FakeClient(volume_exists=True)
    _install_client(monkeypatch, install_transport, client)
    calls: list[tuple[str, bool]] = []

    def run_helper(
        _client: FakeClient,
        resource_image: str,
        script: str,
        *,
        read_only: bool,
    ) -> tuple[int, str]:
        assert resource_image == _RESOURCE_IMAGE
        calls.append((script, read_only))
        return (1, "") if read_only else (0, "")

    monkeypatch.setattr(resources, "_run_helper", run_helper)

    resources.sync(apply=True)
    assert client.images.pulls == 1
    assert client.volumes.created is False
    assert calls[0] == (
        "grep -Fqx -- sha256:0123456789abcdef /dst/.codespace-resource-digest",
        True,
    )
    assert calls[1][1] is True
    assert calls[2][1] is False
    assert calls[2][0].startswith("find /dst -mindepth 1")
    assert calls[2][0].endswith(
        "printf '%s\\n' sha256:0123456789abcdef > /dst/.codespace-resource-digest"
    )
    assert client.closed is True


def test_sync_host_creates_missing_volume(
    monkeypatch: pytest.MonkeyPatch, install_transport: TransportInstaller
) -> None:
    client = FakeClient(volume_exists=False)
    _install_client(monkeypatch, install_transport, client)
    calls: list[bool] = []

    def run_helper(
        _client: FakeClient,
        resource_image: str,
        _script: str,
        *,
        read_only: bool,
    ) -> tuple[int, str]:
        assert resource_image == _RESOURCE_IMAGE
        calls.append(read_only)
        return 0, ""

    monkeypatch.setattr(resources, "_run_helper", run_helper)

    resources.sync(apply=True)
    assert client.images.pulls == 1
    assert client.volumes.created is True
    assert calls == [False]
    assert client.closed is True


def test_sync_host_surfaces_pull_error(
    monkeypatch: pytest.MonkeyPatch, install_transport: TransportInstaller
) -> None:
    client = FakeClient(volume_exists=False, pull_events=[{"error": "registry unavailable"}])
    _install_client(monkeypatch, install_transport, client)

    with pytest.raises(PodmanError, match="registry unavailable"):
        resources.sync(apply=True)

    assert client.closed is True
    assert client.volumes.created is False


def test_sync_host_refills_when_probe_cannot_start(
    monkeypatch: pytest.MonkeyPatch, install_transport: TransportInstaller
) -> None:
    client = FakeClient(volume_exists=True)
    _install_client(monkeypatch, install_transport, client)

    def run_helper(
        _client: FakeClient,
        resource_image: str,
        _script: str,
        *,
        read_only: bool,
    ) -> tuple[int, str]:
        assert resource_image == _RESOURCE_IMAGE
        raise APIError("500 Server Error: Internal Server Error (crun: /bin/sh not found)")

    monkeypatch.setattr(resources, "_run_helper", run_helper)

    resources.sync(apply=False)
    assert client.images.pulls == 0
    assert client.volumes.created is False
    assert client.closed is True


@pytest.mark.parametrize("failure", ["connect", "inventory", "pull", "refresh", "digest"])
def test_sync_host_error_does_not_fill_any_volume(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    install_transport: TransportInstaller,
    failure: str,
) -> None:
    clients = {
        "home": FakeClient(volume_exists=False),
        "office": FakeClient(volume_exists=False),
    }
    if failure == "pull":
        clients["office"].images.events = [{"error": "remote copy failed"}]
    filled: list[FakeClient] = []

    def create_client(host: str) -> FakeClient:
        if host == "office" and failure == "connect":
            raise RuntimeError("remote copy failed")
        return clients[host]

    def exists(_name: str) -> bool:
        if failure == "inventory" or (failure == "refresh" and clients["office"].images.pulls):
            raise RuntimeError("remote copy failed")
        return False

    def missing_digest(_image: str) -> FakeImage:
        image = FakeImage()
        image.attrs.clear()
        return image

    monkeypatch.setattr(resources, "load_config", lambda _path: config)
    install_transport(resources, create_client)
    monkeypatch.setattr(clients["office"].volumes, "exists", exists)
    if failure == "digest":
        monkeypatch.setattr(clients["office"].images, "get", missing_digest)
    monkeypatch.setattr(
        resources, "_fill_volume", lambda client, *_args, **_kwargs: filled.append(client)
    )
    stream = StringIO()

    with pytest.raises(
        (RuntimeError, PodmanError),
        match="has no digest" if failure == "digest" else "remote copy failed",
    ):
        resources.sync(apply=True, console=Console(file=stream, width=120))

    assert filled == []
    assert all(not client.volumes.created for client in clients.values())
    assert clients["home"].closed
    if failure != "connect":
        assert clients["office"].closed
    if failure in {"connect", "inventory"}:
        assert all(client.images.pulls == 0 for client in clients.values())
        assert stream.getvalue() == ""
    else:
        assert "Plan using local images:" in stream.getvalue()
        assert "Plan after pulling images:" not in stream.getvalue()


@pytest.mark.parametrize(
    ("volume_exists", "marker_matches", "force", "apply", "expected"),
    [
        (False, False, False, True, "create"),
        (True, False, False, True, "fill"),
        (True, True, False, True, "skip"),
        (True, True, True, True, "fill"),
        (False, False, False, False, "create"),
    ],
)
def test_sync_checks_all_hosts_before_pulling_and_filling(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    install_transport: TransportInstaller,
    volume_exists: bool,
    marker_matches: bool,
    force: bool,
    apply: bool,
    expected: str,
) -> None:
    clients = {host: FakeClient(volume_exists=volume_exists) for host in sorted(config.hosts)}
    filled: list[FakeClient] = []
    stream = StringIO()

    def pull(images: FakeImages, _image: str, **kwargs: object) -> Iterator[dict[str, str]]:
        assert kwargs == {"stream": True, "decode": True, "policy": "always"}
        assert all(client.volumes.inspections >= 1 for client in clients.values())
        output = stream.getvalue()
        assert "Plan using local images:" in output
        assert "home" in output and "office" in output
        images.pulls += 1
        yield {"status": "pulled"}

    def run_helper(
        client: FakeClient,
        _image: str,
        _script: str,
        *,
        read_only: bool,
    ) -> tuple[int, str]:
        assert not client.closed
        if read_only:
            return (0 if marker_matches else 1), ""
        assert all(item.images.pulls == 1 for item in clients.values())
        assert all(item.volumes.inspections == 2 for item in clients.values())
        assert "Plan after pulling images:" in stream.getvalue()
        filled.append(client)
        return 0, ""

    monkeypatch.setattr(resources, "load_config", lambda _path: config)
    options = install_transport(resources, clients.__getitem__)
    monkeypatch.setattr(FakeImages, "pull", pull)
    monkeypatch.setattr(resources, "_run_helper", run_helper)

    resources.sync(apply=apply, force=force, console=Console(file=stream, width=120))

    assert set(filled) == (set(clients.values()) if apply and expected != "skip" else set())
    assert options == {"hosts": ["home", "office"], "client_timeout": resources._CLIENT_TIMEOUT}
    assert all(
        client.volumes.created == (apply and not volume_exists) for client in clients.values()
    )
    assert all(client.images.pulls == int(apply) for client in clients.values())
    assert all(client.closed for client in clients.values())


def test_sync_scans_pulls_and_fills_hosts_concurrently(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    install_transport: TransportInstaller,
) -> None:
    clients = {host: FakeClient(volume_exists=False) for host in config.hosts}
    scanned = Barrier(len(clients))
    pulled = Barrier(len(clients))
    filled = Barrier(len(clients))
    output = StringIO()

    def exists(self: FakeVolumes, _name: str) -> bool:
        self.inspections += 1
        scanned.wait(timeout=5)
        return False

    def pull(self: FakeImages, _image: str, **_kwargs: object) -> Iterator[dict[str, str]]:
        assert all(client.volumes.inspections == 1 for client in clients.values())
        assert "Plan using local images:" in output.getvalue()
        self.pulls += 1
        pulled.wait(timeout=5)
        yield {"status": "pulled"}

    def fill(client: FakeClient, _image: str, *, action: str, digest: str) -> None:
        assert all(item.volumes.inspections == 2 for item in clients.values())
        assert "Plan after pulling images:" in output.getvalue()
        assert action == "create" and digest == _DIGEST
        filled.wait(timeout=5)
        assert not client.closed
        client.volumes.create(resources.RESOURCE_VOLUME)

    monkeypatch.setattr(resources, "load_config", lambda _path: config)
    monkeypatch.setattr(FakeVolumes, "exists", exists)
    monkeypatch.setattr(FakeImages, "pull", pull)
    monkeypatch.setattr(resources, "_fill_volume", fill)
    install_transport(resources, clients.__getitem__)

    resources.sync(apply=True, console=Console(file=output))

    assert all(client.volumes.created for client in clients.values())
    assert all(client.closed for client in clients.values())
