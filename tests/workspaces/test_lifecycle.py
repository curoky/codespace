"""Tests for Workspace lifecycle orchestration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest
from pydantic import ValidationError

from codespace.config import Config
from codespace.errors import ResourceConflict, ResourceNotFound
from codespace.runtime.host import HostDataPaths
from codespace.runtime.transport import SSHRoute
from codespace.workspaces import agent, inventory, lifecycle, provider, ssh
from codespace.workspaces.agent import WorkspaceAgentClient
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
        state: Literal["awaiting-provider", "ready"],
        *,
        timeout: float,
    ) -> agent.AgentStatus:
        del timeout
        if state == "awaiting-provider":
            return agent.ProviderStatus(state="awaiting-provider", public_key="PUBLIC", error=None)
        return agent.BootstrapStatus(state="ready", public_key=None, error=None)

    def git_state(self) -> RepoGitState:
        return RepoGitState(unpushed=False, uncommitted=True, detail=[" M file"])


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

    assert operation.id == "codespace-workspace_home_codespace_debug"
    assert operation.kind == "workspace"
    assert operation.project == "codespace"
    assert operation.resource == "debug"


@pytest.mark.parametrize("project", ["codespace", "service-api", "scratch", "personal"])
@pytest.mark.parametrize("invalid_status", [False, True])
def test_create_handles_source_bootstrap_and_agent_protocol_failure(
    manager: WorkspaceManager,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    project: str,
    invalid_status: bool,
) -> None:
    host = config.project_hosts(project)[0]
    spec = config.workspace_spec(project, host, "debug")
    manager.queue_create(project, host, "debug")
    events: list[str] = []
    monkeypatch.setattr(inventory, "list_workspaces", lambda *_args: [])
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
    if invalid_status:
        client = WorkspaceAgentClient(Path("/tmp/agent.sock"))
        monkeypatch.setattr(client, "_request", lambda *_args: {})
        monkeypatch.setattr(agent, "WorkspaceAgentClient", lambda _path: client)

    manager.create(project, host, "debug")

    if invalid_status:
        assert events == ["pull", "paths", "control", "create"]
        failed = manager.operations.list()[0]
        assert failed.status == "failed"
        assert "invalid status" in failed.error
        return
    assert events == [
        "pull",
        "paths",
        "control",
        "create",
        *(["register", "ready"] if spec.source.type in {"github", "gitlab"} else []),
        "probe",
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


def test_deletion_check_returns_git_state_without_mutation(
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
    manager._token = lambda _provider: (_ for _ in ()).throw(RuntimeError("token must not be read"))

    state = manager.inspect_deletion("codespace", "home", "debug")

    assert state.uncommitted is True
    assert mutations == []
    assert manager.transport.closed_tcp == []  # type: ignore[attr-defined]


@pytest.mark.parametrize("project", ["codespace", "scratch"])
def test_delete_inspection_never_defaults_an_invalid_agent_response_to_clean(
    manager: WorkspaceManager,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    project: str,
) -> None:
    running = SimpleNamespace(
        id="container-id",
        labels=config.workspace_spec(project, "home", "debug").labels(),
        attrs={"State": {"Status": "running"}},
    )
    requests: list[str] = []
    mutations: list[str] = []
    client = WorkspaceAgentClient(Path("/tmp/agent.sock"))
    monkeypatch.setattr(client, "_request", lambda _method, path: (requests.append(path), {})[-1])
    monkeypatch.setattr(agent, "WorkspaceAgentClient", lambda _path: client)
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(
        lifecycle.container, "remove_container", lambda *_args: mutations.append("remove")
    )
    monkeypatch.setattr(provider, "revoke", lambda *_args: mutations.append("revoke"))

    if project == "scratch":
        assert manager.inspect_deletion(project, "home", "debug").model_dump() == {
            "unpushed": False,
            "uncommitted": False,
            "detail": [],
        }
        assert requests == []
    else:
        with pytest.raises(agent.AgentError, match="invalid Git state"):
            manager.inspect_deletion(project, "home", "debug")
        assert requests == ["/git-state"]
    assert mutations == []


@pytest.mark.parametrize("revoke_fails", [False, True])
def test_purge_revokes_key_before_data_and_container(
    manager: WorkspaceManager,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    revoke_fails: bool,
) -> None:
    events: list[str] = []
    running = SimpleNamespace(
        id="container-id",
        labels=config.workspace_spec("codespace", "home", "debug").labels(),
        attrs={"State": {"Status": "running"}},
        stop=lambda **_kwargs: events.append("stop"),
    )
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)

    def revoke(*_args: object) -> None:
        events.append("revoke")
        if revoke_fails:
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(provider, "revoke", revoke)
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
    if revoke_fails:
        with pytest.raises(RuntimeError, match="provider unavailable"):
            manager.delete("codespace", "home", "debug", purge=True)
        assert events == ["revoke"]
        assert manager.transport.closed_tcp == []  # type: ignore[attr-defined]
        return
    manager.delete("codespace", "home", "debug", purge=True)

    assert events == ["revoke", "stop", "data", "container"]
    assert manager.transport.closed_tcp == [  # type: ignore[attr-defined]
        ("home", "codespace-workspace-24831_home_codespace_debug")
    ]


def test_stopped_workspace_requires_explicit_delete_without_inspection(
    manager: WorkspaceManager, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    mutations: list[str] = []
    running = SimpleNamespace(
        id="container-id",
        labels=config.workspace_spec("personal", "home", "debug").labels(),
        attrs={"State": {"Status": "exited"}},
    )
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(
        lifecycle.container, "remove_container", lambda *_args: mutations.append("container")
    )
    with pytest.raises(ResourceConflict, match="cannot be inspected"):
        manager.inspect_deletion("personal", "home", "debug")
    assert mutations == []

    assert manager.delete("personal", "home", "debug", purge=False) is None
    assert mutations == ["container"]


def test_logs_reads_podman_output(
    manager: WorkspaceManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = SimpleNamespace()
    calls: list[object] = []
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(
        lifecycle.container,
        "container_logs",
        lambda actual: (calls.append(actual), "agent line\n")[-1],
    )

    assert manager.logs("codespace", "home", "debug") == "agent line\n"
    assert calls == [running]


def test_workspace_container_uses_fixed_ssh_listener_and_reserved_mounts(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["container"] = {
        "secrets": [{"source": "atuin_db_uri", "mode": 0o400}],
        "ports": [{"target": 8080, "published": 18080, "host_ip": "127.0.0.1"}],
    }
    spec = Config.model_validate(data).workspace_spec("codespace", "home", "debug")
    original_container = spec.container.model_dump()
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
    assert "SSHD_PORT" not in environment
    assert "SSHD_BIND" not in environment
    assert captured["spec"].ports[-1].model_dump() == {  # type: ignore[union-attr]
        "target": 22,
        "published": spec.ssh_host_port,
        "host_ip": "127.0.0.1",
        "protocol": "tcp",
    }
    targets = {mount["target"] for mount in captured["mounts"]}  # type: ignore[index]
    assert targets == {"/workspace", "/upload", "/cache", "/run/codespace-control"}
    assert [port.target for port in captured["spec"].ports] == [8080, 22]  # type: ignore[union-attr]
    assert spec.container.model_dump() == original_container


def test_workspace_ssh_port_conflict_fails_before_container_creation(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = config.model_dump()
    data["projects"]["scratch"]["container"] = {
        "ports": [{"target": 22, "published": 2222, "host_ip": "127.0.0.1"}],
    }
    spec = Config.model_validate(data).workspace_spec("scratch", "home", "debug")
    created: list[object] = []
    monkeypatch.setattr(
        lifecycle.container, "create_container", lambda *_args, **kwargs: created.append(kwargs)
    )

    with pytest.raises(ValidationError, match="22/tcp is published more than once"):
        lifecycle._create_workspace_container(
            SimpleNamespace(),  # type: ignore[arg-type]
            spec,
            _PATHS.workspace("scratch", "debug"),
            {},
        )

    assert created == []


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
    assert spec.container.secrets == []
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
    monkeypatch.setattr(provider, "revoke", lambda *args: revoked.append(args))
    monkeypatch.setattr(lifecycle.container, "remove_container", lambda _container: None)

    assert manager.inspect_deletion("codespace", "home", "debug").uncommitted
    manager.delete("codespace", "home", "debug", purge=False)

    assert revoked == [
        ("github", "token", "curoky/codespace", "codespace-workspace_home_codespace_debug")
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
            actual.ssh_alias,
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

    with pytest.raises(ResourceConflict, match="is not running"):
        manager.open_tunnel("codespace", "home", "debug", 8005)
    assert manager.transport.tcp_forwards == []  # type: ignore[attr-defined]


def test_tunnel_rejects_unconfigured_port(
    manager: WorkspaceManager, tunnel_container: SimpleNamespace
) -> None:
    with pytest.raises(ResourceNotFound, match="not configured"):
        manager.open_tunnel("codespace", "home", "debug", 22)
    assert manager.transport.tcp_forwards == []  # type: ignore[attr-defined]


def test_tunnel_rejects_missing_workspace(
    manager: WorkspaceManager, tunnel_container: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: None)
    with pytest.raises(ResourceNotFound, match="not found"):
        manager.open_tunnel("codespace", "home", "debug", 8005)
    assert manager.transport.tcp_forwards == []  # type: ignore[attr-defined]
