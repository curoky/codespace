"""Tests for resource-volume synchronization over podman-py SSH connections."""

from __future__ import annotations

from collections.abc import Iterator
from io import StringIO

import pytest
from podman.errors import APIError, PodmanError
from rich.console import Console

from codespace.config import Config
from codespace.maintenance import resources

_RESOURCE_IMAGE = "ghcr.io/curoky/codespace:workspace-resource"
_DIGEST = "sha256:0123456789abcdef"
_UPDATED_DIGEST = "sha256:fedcba9876543210"


class FakeVolumes:
    def __init__(self, existing: bool) -> None:
        self.existing = existing
        self.created = False

    def exists(self, _name: str) -> bool:
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

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(
        self,
        _exc_type: object,
        _exc_value: object,
        _traceback: object,
    ) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True


def _install_client(
    monkeypatch: pytest.MonkeyPatch,
    client: FakeClient,
) -> dict[str, object]:
    options: dict[str, object] = {}

    def create_client(**kwargs: object) -> FakeClient:
        options.update(kwargs)
        return client

    monkeypatch.setattr(resources, "PodmanClient", create_client)
    return options


def test_sync_host_uses_direct_podman_ssh_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(volume_exists=True)
    options = _install_client(monkeypatch, client)
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

    assert (
        resources._sync_host(
            "home",
            resource_image=_RESOURCE_IMAGE,
            apply=False,
            force=False,
        )
        == "skip"
    )
    assert options == {
        "base_url": "http+ssh://home/run/podman/podman.sock",
        "timeout": resources._CLIENT_TIMEOUT,
    }
    assert scripts == ["grep -Fqx -- sha256:0123456789abcdef /dst/.codespace-resource-digest"]
    assert client.images.requested == [("get", _RESOURCE_IMAGE)]
    assert client.images.pulls == 0
    assert client.closed is True


def test_sync_host_pulls_before_comparing_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(volume_exists=True)
    _install_client(monkeypatch, client)
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

    assert (
        resources._sync_host(
            "home",
            resource_image=_RESOURCE_IMAGE,
            apply=True,
            force=False,
        )
        == "fill"
    )
    assert client.images.pulls == 1
    assert _UPDATED_DIGEST in scripts[0]
    assert scripts[-1].endswith(
        f"printf '%s\\n' {_UPDATED_DIGEST} > /dst/.codespace-resource-digest"
    )


def test_sync_host_pulls_and_fills_existing_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(volume_exists=True)
    _install_client(monkeypatch, client)
    calls: list[tuple[str, bool]] = []
    stages: list[str] = []

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

    assert (
        resources._sync_host(
            "home",
            resource_image=_RESOURCE_IMAGE,
            apply=True,
            force=False,
            stage=stages.append,
        )
        == "fill"
    )
    assert client.images.pulls == 1
    assert client.volumes.created is False
    assert stages == [
        "connecting",
        "pulling image",
        "checking volume",
        "checking digest",
        "filling volume",
    ]
    assert calls[0] == (
        "grep -Fqx -- sha256:0123456789abcdef /dst/.codespace-resource-digest",
        True,
    )
    assert calls[1][1] is False
    assert calls[1][0].startswith("find /dst -mindepth 1")
    assert calls[1][0].endswith(
        "printf '%s\\n' sha256:0123456789abcdef > /dst/.codespace-resource-digest"
    )
    assert client.closed is True


def test_sync_host_creates_missing_volume(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(volume_exists=False)
    _install_client(monkeypatch, client)
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

    assert (
        resources._sync_host(
            "home",
            resource_image=_RESOURCE_IMAGE,
            apply=True,
            force=False,
        )
        == "create"
    )
    assert client.images.pulls == 1
    assert client.volumes.created is True
    assert calls == [False]
    assert client.closed is True


def test_sync_host_surfaces_pull_error(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(volume_exists=False, pull_events=[{"error": "registry unavailable"}])
    _install_client(monkeypatch, client)

    with pytest.raises(PodmanError, match="registry unavailable"):
        resources._sync_host(
            "home",
            resource_image=_RESOURCE_IMAGE,
            apply=True,
            force=False,
        )

    assert client.closed is True


def test_sync_host_refills_when_probe_cannot_start(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(volume_exists=True)
    _install_client(monkeypatch, client)

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

    assert (
        resources._sync_host(
            "home",
            resource_image=_RESOURCE_IMAGE,
            apply=False,
            force=False,
        )
        == "fill"
    )
    assert client.closed is True


def test_sync_fails_on_host_error(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def sync_host(
        host: str,
        *,
        resource_image: str,
        apply: bool,
        force: bool,
        stage: object,
    ) -> resources.Action:
        assert resource_image == config.project_defaults.resource_image
        if host == "office":
            raise RuntimeError("remote copy failed")
        return "fill"

    monkeypatch.setattr(resources, "load_config", lambda _path: config)
    monkeypatch.setattr(resources, "_sync_host", sync_host)
    stream = StringIO()

    with pytest.raises(RuntimeError, match="remote copy failed"):
        resources.sync(apply=True, console=Console(file=stream, width=120))

    assert stream.getvalue() == ""
