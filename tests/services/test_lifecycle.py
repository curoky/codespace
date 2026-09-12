"""Tests for Service reconcile and removal."""

from types import SimpleNamespace

import pytest

from codespace import control as lifecycle
from codespace.config import Config
from codespace.control import ControlPlane
from codespace.resources import Resource
from codespace.runtime.host import HostDataPaths
from codespace.runtime.transport import SSHRoute


class FakeTransport:
    client_value = SimpleNamespace()

    def __init__(self) -> None:
        self.tcp_forwards: list[tuple[str, str, dict[str, object]]] = []

    def client(self, _host: str) -> object:
        return self.client_value

    def ssh_route(self, host: str) -> SSHRoute:
        return SSHRoute(host=host)

    def forward_tcp(self, host: str, destination: str, **kwargs: object) -> int:
        self.tcp_forwards.append((host, destination, kwargs))
        return 49123


@pytest.fixture
def manager(config: Config) -> ControlPlane:
    return ControlPlane(config, transport=FakeTransport())  # type: ignore[arg-type]


def test_apply_replaces_container_and_resolves_data_placeholder(
    manager: ControlPlane,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    running = SimpleNamespace()
    captured: dict[str, object] = {}
    manager.queue(Resource("office", "vllm"))
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

    manager.deploy(Resource("office", "vllm"))

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


def test_apply_failure_is_retained(manager: ControlPlane, monkeypatch: pytest.MonkeyPatch) -> None:
    manager.queue(Resource("home", "support"))
    monkeypatch.setattr(
        lifecycle.container,
        "find_container",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Podman unavailable")),
    )

    manager.deploy(Resource("home", "support"))

    failed = manager.operations.list()[0]
    assert failed.kind == "service"
    assert failed.status == "failed"
    assert failed.error == "RuntimeError: Podman unavailable"


def test_remove_can_purge_service_data(
    manager: ControlPlane,
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

    assert manager.remove(Resource("home", "support"), purge=True) is True
    assert events == ["container", "data"]


def test_logs_reads_podman_output(
    manager: ControlPlane,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = SimpleNamespace()
    calls: list[object] = []
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(
        lifecycle.container,
        "container_logs",
        lambda actual: (calls.append(actual), "service line\n")[-1],
    )

    assert manager.logs(Resource("home", "support")) == "service line\n"
    assert calls == [running]


def test_tunnel_forwards_explicitly_configured_loopback_port(
    manager: ControlPlane,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = config.model_dump()
    data["services"]["support"]["container"] = {
        "ports": [{"target": 8080, "published": 8110, "host_ip": "127.0.0.1"}]
    }
    manager.config = Config.model_validate(data)
    running = SimpleNamespace(
        id="deployed-container",
        labels=manager.config.service_spec("support", "home").labels(),
        attrs={"State": {"Status": "running"}},
    )
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)

    assert manager.open_tunnel(Resource("home", "support"), 8110) == 49123
    assert manager.transport.tcp_forwards == [  # type: ignore[attr-defined]
        (
            "home",
            "home",
            {
                "port": 8110,
                "local_port": 8110,
                "remote_host": "127.0.0.1",
                "options": [],
                "connection_id": "deployed-container",
            },
        )
    ]


def test_tunnel_rejects_unpublished_service_port(
    manager: ControlPlane,
) -> None:
    with pytest.raises(lifecycle.ResourceNotFound, match="not configured"):
        manager.open_tunnel(Resource("home", "support"), 8110)


def test_tunnel_rejects_stopped_service(
    manager: ControlPlane,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = manager.config.model_dump()
    data["services"]["support"]["container"] = {
        "ports": [{"target": 8080, "published": 8110, "host_ip": "127.0.0.1"}]
    }
    manager.config = Config.model_validate(data)
    running = SimpleNamespace(
        id="deployed-container",
        labels=manager.config.service_spec("support", "home").labels(),
        attrs={"State": {"Status": "exited"}},
    )
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)

    with pytest.raises(lifecycle.ResourceConflict, match="is not running"):
        manager.open_tunnel(Resource("home", "support"), 8110)
