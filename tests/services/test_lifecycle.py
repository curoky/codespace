"""Tests for Service reconcile and removal."""

from types import SimpleNamespace

import pytest

from codespace.config import Config
from codespace.runtime.host import HostDataPaths
from codespace.runtime.transport import SSHRoute
from codespace.services import lifecycle
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
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
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
    assert captured["mounts"] == []
    runtime_spec = captured["spec"]
    assert runtime_spec.volumes[0].mount() == {  # type: ignore[union-attr]
        "type": "bind",
        "source": "/home/x/codespace/services/vllm",
        "target": "/root/.cache/huggingface",
        "read_only": False,
    }
    assert captured["restart_policy"] == {"Name": "unless-stopped"}
    assert manager.operations.list() == []


def test_apply_failure_is_retained(
    manager: ServiceManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager.queue_apply("support", "home")
    monkeypatch.setattr(
        lifecycle.container,
        "find_container",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Podman unavailable")),
    )

    manager.apply("support", "home")

    failed = manager.operations.list()[0]
    assert failed.kind == "service"
    assert failed.status == "failed"
    assert failed.error == "RuntimeError: Podman unavailable"


def test_remove_can_purge_service_data(
    manager: ServiceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(
        lifecycle.container, "find_container", lambda *_args, **_kwargs: SimpleNamespace()
    )
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


def test_logs_reads_selected_container_source(
    manager: ServiceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = SimpleNamespace()
    snapshot = lifecycle.container.LogSnapshot(
        source="s6.atuin-service.log",
        sources=("container", "s6.atuin-service.log"),
        logs="service line\n",
    )
    calls: list[tuple[object, str]] = []
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(
        lifecycle.container,
        "container_log_snapshot",
        lambda actual, source: (calls.append((actual, source)), snapshot)[-1],
    )

    assert manager.logs("support", "home", "s6.atuin-service.log") is snapshot
    assert calls == [(running, "s6.atuin-service.log")]
