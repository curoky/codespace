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
from codespace.workspaces.models import RepoGitState, Workspace

_PATHS = HostDataPaths("/home/x/codespace")


class FakeTransport:
    def __init__(self) -> None:
        self.client_value = object()

    def client(self, _host: str) -> object:
        return self.client_value

    def ssh_route(self, host: str) -> SSHRoute:
        return SSHRoute(host=host)

    def forward_socket(self, host: str, _remote: str) -> Path:
        return Path(f"/tmp/{host}-agent.sock")


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


def _workspace(config: Config, name: str = "debug") -> Workspace:
    return config.workspace_spec("codespace", "home", name).to_workspace(
        "container-id",
        status="running",
    )


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


def test_create_runs_provider_handshake_and_clears_operation(
    manager: WorkspaceManager,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager.queue_create("codespace", "home", "debug")
    events: list[str] = []
    inventories = iter([[], [_workspace(config)]])
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

    manager.create("codespace", "home", "debug")

    assert events == [
        "pull",
        "paths",
        "control",
        "create",
        "register",
        "ready",
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
    running = SimpleNamespace()
    mutations: list[str] = []
    monkeypatch.setattr(inventory, "list_workspaces", lambda *_args: [_workspace(config)])
    monkeypatch.setattr(inventory, "find_container", lambda *_args: running)
    monkeypatch.setattr(
        lifecycle.container, "remove_container", lambda *_args: mutations.append("remove")
    )

    state = manager.delete("codespace", "home", "debug", purge=True)

    assert state.uncommitted is True
    assert mutations == []


def test_forced_purge_revokes_key_before_data_and_container(
    manager: WorkspaceManager,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    running = SimpleNamespace(stop=lambda **_kwargs: events.append("stop"))
    inventories = iter([[_workspace(config)], []])
    monkeypatch.setattr(inventory, "list_workspaces", lambda *_args: next(inventories))
    monkeypatch.setattr(inventory, "find_container", lambda *_args: running)
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


def test_workspace_container_uses_reserved_environment_and_mounts(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = config.workspace_spec("codespace", "home", "debug")
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
    assert environment["CODESPACE_CLONE_URL"] == "git@github.com:curoky/codespace.git"
    targets = {mount["target"] for mount in captured["mounts"]}  # type: ignore[index]
    assert {"/workspace", "/upload", "/cache", "/run/codespace-control"} <= targets
