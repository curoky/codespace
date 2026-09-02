"""Tests for Service reconcile and removal."""

from types import SimpleNamespace

import pytest

from codespace.config import Config
from codespace.runtime.host import HostDataPaths
from codespace.runtime.transport import SSHRoute
from codespace.services import inventory, lifecycle
from codespace.services.lifecycle import ServiceManager


class FakeTransport:
    client_value = SimpleNamespace()

    def client(self, _host: str) -> object:
        return self.client_value

    def ssh_route(self, host: str) -> SSHRoute:
        return SSHRoute(host=host)


@pytest.fixture
def manager(config: Config) -> ServiceManager:
    return ServiceManager(config, FakeTransport())  # type: ignore[arg-type]


def test_apply_replaces_container_and_resolves_data_placeholder(
    manager: ServiceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    running = SimpleNamespace()
    captured: dict[str, object] = {}
    manager.queue_apply("vllm", "office")
    monkeypatch.setattr(lifecycle.container, "pull_image", lambda *_args: events.append("pull"))
    monkeypatch.setattr(
        lifecycle.host,
        "remote_data_paths",
        lambda _route: HostDataPaths("/home/x/codespace"),
    )
    monkeypatch.setattr(
        lifecycle.host,
        "prepare_directories",
        lambda _route, paths: events.append(paths[0]),
    )
    monkeypatch.setattr(
        inventory,
        "list_services",
        lambda *_args: [
            SimpleNamespace(id="codespace-service-vllm"),
        ],
    )
    monkeypatch.setattr(inventory, "find_container", lambda *_args: running)
    monkeypatch.setattr(
        lifecycle.container,
        "remove_container",
        lambda _running: events.append("remove"),
    )
    monkeypatch.setattr(
        lifecycle.container,
        "create_container",
        lambda *_args, **kwargs: captured.update(kwargs),
    )

    manager.apply("vllm", "office")

    assert events == ["pull", "/home/x/codespace/services/vllm", "remove"]
    assert captured["name"] == "codespace-service-vllm"
    assert captured["volume_placeholders"] == {"${SERVICE_DATA}": "/home/x/codespace/services/vllm"}
    assert captured["restart_policy"] == {"Name": "unless-stopped"}
    assert manager.operations.list() == []


def test_remove_can_purge_service_data(
    manager: ServiceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        inventory,
        "list_services",
        lambda *_args: [
            SimpleNamespace(id="codespace-service-support"),
        ],
    )
    monkeypatch.setattr(inventory, "find_container", lambda *_args: SimpleNamespace())
    monkeypatch.setattr(
        lifecycle.container,
        "remove_container",
        lambda _running: events.append("container"),
    )
    monkeypatch.setattr(
        lifecycle.host,
        "remote_data_paths",
        lambda _route: HostDataPaths("/home/x/codespace"),
    )
    monkeypatch.setattr(
        lifecycle.container,
        "remove_data_directory",
        lambda *_args: events.append("data"),
    )

    assert manager.remove("support", "home", purge=True) is True
    assert events == ["container", "data"]
