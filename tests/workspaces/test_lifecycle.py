"""Tests for Workspace lifecycle orchestration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from codespace.config import Config
from codespace.runtime.host import HostDataPaths
from codespace.runtime.transport import SSHRoute
from codespace.workspaces import agent, inventory, lifecycle, provider, ssh
from codespace.workspaces.lifecycle import WorkspaceManager
from codespace.workspaces.models import RepoGitState

_PATHS = HostDataPaths("/home/x/codespace")


class FakeTransport:
    def __init__(self) -> None:
        self.client_value = object()
        self.tcp_forwards: list[tuple[str, str, dict[str, object]]] = []
        self.closed_tcp: list[tuple[str, str]] = []

    def client(self, _host: str) -> object:
        return self.client_value

    def ssh_route(self, host: str) -> SSHRoute:
        return SSHRoute(host=host)

    def forward_socket(self, host: str, _remote: str) -> Path:
        return Path(f"/tmp/{host}-agent.sock")

    def forward_tcp(self, host: str, destination: str, **kwargs: object) -> int:
        self.tcp_forwards.append((host, destination, kwargs))
        return 49123

    def close_tcp(self, host: str, destination: str) -> None:
        self.closed_tcp.append((host, destination))


class FakeAgent:
    def __init__(self, _path: Path) -> None:
        return None

    def wait_for(
        self,
        states: set[agent.AgentState],
        *,
        timeout: float,
    ) -> agent.AgentStatus:
        del timeout
        if "awaiting-provider" in states:
            return agent.AgentStatus(state="awaiting-provider", public_key="PUBLIC")
        return agent.AgentStatus(state="ready")

    def git_state(self) -> RepoGitState:
        return RepoGitState(uncommitted=True, detail=[" M file"])


@pytest.fixture
def manager(config: Config, monkeypatch: pytest.MonkeyPatch) -> WorkspaceManager:
    monkeypatch.setattr(agent, "WorkspaceAgentClient", FakeAgent)
    monkeypatch.setattr(lifecycle.host, "remote_data_paths", lambda _route: _PATHS)
    return WorkspaceManager(
        config,
        FakeTransport(),  # type: ignore[arg-type]
        lambda _provider: "token",
    )


def test_queue_create_uses_final_identity(manager: WorkspaceManager) -> None:
    operation = manager.queue_create("codespace", "home", "debug")

    assert operation.id == "codespace-workspace-home-codespace-debug"
    assert operation.kind == "workspace"
    assert operation.project == "codespace"
    assert operation.resource == "debug"


@pytest.mark.parametrize("project", ["codespace", "service-api", "scratch", "personal"])
def test_create_runs_source_bootstrap_and_clears_operation(
    manager: WorkspaceManager,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    project: str,
) -> None:
    host = config.project_hosts(project)[0]
    spec = config.workspace_spec(project, host, "debug")
    manager.queue_create(project, host, "debug")
    events: list[str] = []
    inventories = iter([[], [spec.to_workspace("container-id", status="running")]])
    monkeypatch.setattr(inventory, "list_workspaces", lambda *_args: next(inventories))
    monkeypatch.setattr(lifecycle.host, "read_environment", lambda *_args: {"HTTP_PROXY": "proxy"})
    monkeypatch.setattr(
        lifecycle.host, "prepare_directories", lambda *_args: events.append("paths")
    )
    monkeypatch.setattr(
        lifecycle.host,
        "reset_workspace_control",
        lambda *_args: events.append("control"),
    )
    monkeypatch.setattr(
        lifecycle.host,
        "signal_provider_ready",
        lambda *_args: events.append("ready"),
    )
    monkeypatch.setattr(lifecycle.container, "pull_image", lambda *_args: events.append("pull"))
    monkeypatch.setattr(
        lifecycle,
        "_create_workspace_container",
        lambda *_args: (events.append("create"), SimpleNamespace(id="container-id"))[-1],
    )
    monkeypatch.setattr(provider, "register", lambda *_args: events.append("register"))
    monkeypatch.setattr(ssh, "probe", lambda *_args: events.append("probe"))
    monkeypatch.setattr(ssh, "write_host", lambda *_args: events.append("projection"))

    manager.create(project, host, "debug")

    assert events == [
        "pull",
        "paths",
        "control",
        "create",
        *(["register", "ready"] if spec.source.type in {"github", "gitlab"} else []),
        "probe",
        "projection",
    ]
    assert manager.operations.list() == []


def test_create_failure_is_retained_as_failed_operation(
    manager: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager.queue_create("codespace", "home", "debug")
    monkeypatch.setattr(
        inventory,
        "list_workspaces",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("Podman unavailable")),
    )

    manager.create("codespace", "home", "debug")

    assert manager.operations.list()[0].status == "failed"
    assert "Podman unavailable" in (manager.operations.list()[0].error or "")


def test_unforced_delete_returns_git_state_without_mutation(
    manager: WorkspaceManager,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = SimpleNamespace(
        id="container-id",
        labels=config.workspace_spec("codespace", "home", "debug").labels(),
        attrs={"State": {"Status": "running"}},
    )
    mutations: list[str] = []
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(
        lifecycle.container, "remove_container", lambda *_args: mutations.append("remove")
    )

    state = manager.delete("codespace", "home", "debug", purge=True)

    assert state.uncommitted is True
    assert mutations == []
    assert manager.transport.closed_tcp == []  # type: ignore[attr-defined]


def test_forced_purge_revokes_key_before_data_and_container(
    manager: WorkspaceManager,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    running = SimpleNamespace(
        id="container-id",
        labels=config.workspace_spec("codespace", "home", "debug").labels(),
        attrs={"State": {"Status": "running"}},
        stop=lambda **_kwargs: events.append("stop"),
    )
    monkeypatch.setattr(inventory, "list_workspaces", lambda *_args: [])
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(provider, "revoke", lambda *_args: events.append("revoke"))
    monkeypatch.setattr(
        lifecycle.container,
        "remove_data_directory",
        lambda *_args, **_kwargs: events.append("data"),
    )
    monkeypatch.setattr(
        lifecycle.container,
        "remove_container",
        lambda *_args: events.append("container"),
    )
    monkeypatch.setattr(ssh, "write_host", lambda *_args: events.append("projection"))

    manager.delete("codespace", "home", "debug", purge=True, force=True)

    assert events == ["revoke", "stop", "data", "container", "projection"]
    assert manager.transport.closed_tcp == [  # type: ignore[attr-defined]
        ("home", "codespace-workspace-home-codespace-debug")
    ]


def test_logs_reads_selected_container_source(
    manager: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = SimpleNamespace()
    snapshot = lifecycle.container.LogSnapshot(
        source="s6.workspace-agent.log",
        sources=("container", "s6.workspace-agent.log"),
        logs="agent line\n",
    )
    calls: list[tuple[object, str]] = []
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(
        lifecycle.container,
        "container_log_snapshot",
        lambda actual, source: (calls.append((actual, source)), snapshot)[-1],
    )

    assert manager.logs("codespace", "home", "debug", "s6.workspace-agent.log") is snapshot
    assert calls == [(running, "s6.workspace-agent.log")]


@pytest.mark.parametrize("network_mode", ["host", "bridge"])
def test_workspace_container_uses_reserved_environment_and_mounts(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    network_mode: str,
) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["container"] = {
        "network_mode": network_mode,
        "secrets": [{"source": "atuin_db_uri", "mode": 0o400}],
    }
    spec = Config.model_validate(data).workspace_spec("codespace", "home", "debug")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        lifecycle.container,
        "create_container",
        lambda *_args, **kwargs: (captured.update(kwargs), SimpleNamespace())[-1],
    )

    lifecycle._create_workspace_container(
        SimpleNamespace(),  # type: ignore[arg-type]
        spec,
        _PATHS.workspace("codespace", "debug"),
        {"HTTP_PROXY": "proxy"},
    )

    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert environment["CODESPACE_SOURCE_TYPE"] == "github"
    assert environment["CODESPACE_CHECKOUT_PATH"] == "/workspace/codespace"
    assert environment["CODESPACE_OPEN_PATH"] == "/workspace/codespace"
    assert environment["CODESPACE_ENCRYPTED"] == "false"
    assert environment["CODESPACE_CLONE_URL"] == "git@github.com:curoky/codespace.git"
    assert "ATUIN_SYNC_ADDRESS" not in environment
    assert captured["spec"].secrets[0].source == "atuin_db_uri"  # type: ignore[union-attr]
    assert captured["spec"].secrets[0].mode == 0o400  # type: ignore[union-attr]
    assert environment["SSHD_PORT"] == str(spec.ssh_port)
    if network_mode == "bridge":
        assert environment["SSHD_BIND"] == "0.0.0.0"  # noqa: S104
        assert captured["extra_ports"] == {f"{spec.ssh_port}/tcp": ("127.0.0.1", spec.ssh_port)}
    else:
        assert "SSHD_BIND" not in environment
        assert captured["extra_ports"] == {}
    targets = {mount["target"] for mount in captured["mounts"]}  # type: ignore[index]
    assert {"/workspace", "/upload", "/cache", "/run/codespace-control"} <= targets
    assert {
        f"/home/x/{home}/{child}"
        for home in (
            ".vscode-server",
            ".trae",
            ".trae-cn",
            ".trae-server",
            ".trae-cn-server",
        )
        for child in ("bin", "extensions")
    } <= targets
    assert (
        not {
            "/home/x/.vscode-server",
            "/home/x/.trae",
            "/home/x/.trae-cn",
            "/home/x/.trae-server",
            "/home/x/.trae-cn-server",
        }
        & targets
    )


def test_encrypted_workspace_mounts_key_as_compose_secret(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["encrypted"] = True
    data["secrets"]["codespace_workspace_key"] = "test-key"
    spec = Config.model_validate(data).workspace_spec("codespace", "home", "debug")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        lifecycle.container,
        "create_container",
        lambda *_args, **kwargs: (captured.update(kwargs), SimpleNamespace())[-1],
    )

    lifecycle._create_workspace_container(
        SimpleNamespace(),  # type: ignore[arg-type]
        spec,
        _PATHS.workspace("codespace", "debug"),
        {},
    )

    runtime_spec = captured["spec"]
    assert captured["environment"]["CODESPACE_ENCRYPTED"] == "true"  # type: ignore[index]
    assert captured["labels"]["codespace.encrypted"] == "true"  # type: ignore[index]
    assert runtime_spec.secrets is not None  # type: ignore[union-attr]
    assert runtime_spec.secrets[0].model_dump() == {  # type: ignore[union-attr]
        "source": "codespace_workspace_key",
        "target": None,
        "uid": "5230",
        "gid": "5230",
        "mode": 0o400,
    }


def test_delete_uses_deployed_source_after_config_changes(
    manager: WorkspaceManager, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    running = SimpleNamespace(
        id="container-id",
        labels=config.workspace_spec("codespace", "home", "debug").labels(),
        attrs={"State": {"Status": "running"}},
    )
    data = config.model_dump()
    data["projects"]["codespace"]["source"] = {"type": "empty"}
    manager.config = Config.model_validate(data)
    revoked: list[tuple[str, ...]] = []
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(inventory, "list_workspaces", lambda *_args: [])
    monkeypatch.setattr(provider, "revoke", lambda *args: revoked.append(args))
    monkeypatch.setattr(lifecycle.container, "remove_container", lambda _container: None)
    monkeypatch.setattr(ssh, "write_host", lambda *_args: None)

    assert manager.delete("codespace", "home", "debug", purge=False).uncommitted
    manager.delete("codespace", "home", "debug", purge=False, force=True)

    assert revoked == [
        ("github", "token", "curoky/codespace", "codespace-workspace-home-codespace-debug")
    ]


@pytest.fixture
def tunnel_container(
    manager: WorkspaceManager, config: Config, monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    running = SimpleNamespace(
        id="deployed-container",
        labels=config.workspace_spec("codespace", "home", "debug").labels(),
        attrs={"State": {"Status": "running"}},
    )
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    data = config.model_dump()
    data["project_defaults"]["tunnel_ports"] = [8005, 8080]
    manager.config = Config.model_validate(data)
    return running


@pytest.mark.parametrize("port", [8005, 8080])
def test_tunnel_uses_configured_port_and_deployed_ssh_metadata(
    manager: WorkspaceManager,
    tunnel_container: SimpleNamespace,
    port: int,
) -> None:
    actual = inventory.read_workspace(tunnel_container, "home")

    assert manager.open_tunnel("codespace", "home", "debug", port) == 49123
    assert manager.transport.tcp_forwards == [  # type: ignore[attr-defined]
        (
            "home",
            actual.id,
            {
                "port": port,
                "options": ssh.connection_options(actual, SSHRoute(host="home")),
                "connection_id": "deployed-container",
            },
        )
    ]
    assert manager.transport.closed_tcp == []  # type: ignore[attr-defined]


@pytest.mark.parametrize("status", ["exited", "paused", "created"])
def test_tunnel_rejects_nonrunning_workspace(
    manager: WorkspaceManager, tunnel_container: SimpleNamespace, status: str
) -> None:
    tunnel_container.attrs["State"]["Status"] = status

    with pytest.raises(RuntimeError, match="is not running"):
        manager.open_tunnel("codespace", "home", "debug", 8005)
    assert manager.transport.tcp_forwards == []  # type: ignore[attr-defined]


def test_tunnel_rejects_unconfigured_port(
    manager: WorkspaceManager, tunnel_container: SimpleNamespace
) -> None:
    with pytest.raises(KeyError, match="not configured"):
        manager.open_tunnel("codespace", "home", "debug", 22)
    assert manager.transport.tcp_forwards == []  # type: ignore[attr-defined]


def test_tunnel_rejects_missing_workspace(
    manager: WorkspaceManager, tunnel_container: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: None)
    with pytest.raises(RuntimeError, match="not found"):
        manager.open_tunnel("codespace", "home", "debug", 8005)
    assert manager.transport.tcp_forwards == []  # type: ignore[attr-defined]
