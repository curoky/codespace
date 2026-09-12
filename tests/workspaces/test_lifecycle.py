"""Tests for Workspace lifecycle orchestration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest

from codespace import workspaces as inventory
from codespace.config import Config
from codespace.control import ControlPlane
from codespace.resources import Resource, ResourceConflict, ResourceNotFound
from codespace.runtime import host as host_runtime
from codespace.runtime.host import HostDataPaths
from codespace.runtime.transport import SSHRoute
from codespace.workspaces import RepoGitState, agent, lifecycle, provider, ssh
from codespace.workspaces.agent import WorkspaceAgentClient

_PATHS = HostDataPaths("/home/x/codespace")
_CACHE_PATHS = (
    ".vscode-server/cli",
    ".vscode-server/extensions",
    ".trae/bin",
    ".trae/extensions",
    ".trae-cn/bin",
    ".trae-cn/extensions",
    ".trae-server/bin",
    ".trae-server/extensions",
    ".trae-cn-server/bin",
    ".trae-cn-server/extensions",
)


class FakeTransport:
    def __init__(self) -> None:
        self.client_value = object()
        self.socket_forwards: list[tuple[str, str]] = []
        self.tcp_forwards: list[tuple[str, str, dict[str, object]]] = []
        self.closed_tcp: list[tuple[str, str]] = []

    def client(self, _host: str) -> object:
        return self.client_value

    def ssh_route(self, host: str) -> SSHRoute:
        return SSHRoute(host=host)

    def forward_socket(self, host: str, remote: str) -> Path:
        self.socket_forwards.append((host, remote))
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

    def authorize_provider(self) -> None:
        pass


@pytest.fixture
def manager(config: Config, monkeypatch: pytest.MonkeyPatch) -> ControlPlane:
    monkeypatch.setattr(agent, "WorkspaceAgentClient", FakeAgent)
    monkeypatch.setattr(host_runtime, "remote_data_paths", lambda _route: _PATHS)
    monkeypatch.setattr(ssh, "write_route", lambda _workspace: None)
    monkeypatch.setattr(ssh, "remove_route", lambda _workspace: None)
    control = ControlPlane(config, transport=FakeTransport())  # type: ignore[arg-type]
    control.set_token("github", "token")
    control.set_token("gitlab", "token")
    return control


def test_container_name_collision_fails_before_creation(
    manager: ControlPlane, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = config.workspace_spec("scratch", "home", "a-b")
    existing = spec.to_workspace("existing", status="running").model_copy(
        update={"project": "scratch-a", "workspace": "b"}
    )
    monkeypatch.setattr(lifecycle, "list_workspaces", lambda *_args: [existing])
    manager.queue(Resource("home", "a-b", "scratch"))
    manager.deploy(Resource("home", "a-b", "scratch"))
    failed = manager.operations.list()[0]
    assert failed.status == "failed"
    assert "container name collision" in (failed.error or "")


def test_container_lookup_uses_short_name_and_ownership_labels(
    manager: ControlPlane, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[tuple[str, dict[str, str]]] = []

    def lookup(_client: object, name: str, *, labels: dict[str, str]) -> None:
        captured.append((name, labels))

    monkeypatch.setattr(lifecycle.container, "find_container", lookup)
    with pytest.raises(ResourceNotFound):
        manager.logs(Resource("home", "debug", "codespace"))
    assert captured == [
        (
            "space-codespace-debug",
            {
                "codespace.kind": "workspace",
                "codespace.project": "codespace",
                "codespace.workspace": "debug",
            },
        )
    ]


def test_queue_create_uses_final_identity(manager: ControlPlane) -> None:
    operation = manager.queue(Resource("home", "debug", "codespace"))

    assert operation.id == "space:codespace/debug@home"
    assert operation.kind == "workspace"
    assert operation.project == "codespace"
    assert operation.resource == "debug"


@pytest.mark.parametrize("project", ["codespace", "service-api", "scratch", "personal"])
@pytest.mark.parametrize("invalid_status", [False, True])
def test_create_handles_source_bootstrap_and_agent_protocol_failure(
    manager: ControlPlane,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    project: str,
    invalid_status: bool,
) -> None:
    host = next(iter(config.projects[project].hosts))
    spec = config.workspace_spec(project, host, "debug")
    manager.queue(Resource(host, "debug", project))
    events: list[str] = []
    directories: list[str] = []
    monkeypatch.setattr(lifecycle, "list_workspaces", lambda *_args: [])
    monkeypatch.setattr(host_runtime, "read_environment", lambda *_args: {"HTTP_PROXY": "proxy"})
    monkeypatch.setattr(
        host_runtime,
        "prepare_directories",
        lambda _route, paths: (directories.extend(paths), events.append("paths")),
    )
    monkeypatch.setattr(
        FakeAgent,
        "authorize_provider",
        lambda *_args: events.append("ready"),
    )
    monkeypatch.setattr(lifecycle.container, "pull_image", lambda *_args: events.append("pull"))
    monkeypatch.setattr(
        lifecycle,
        "create_container",
        lambda *_args: (events.append("create"), SimpleNamespace(id="container-id"))[-1],
    )
    monkeypatch.setattr(provider, "register", lambda *_args: events.append("register"))
    monkeypatch.setattr(ssh, "write_route", lambda _workspace: events.append("route"))
    if invalid_status:
        client = WorkspaceAgentClient(Path("/tmp/agent.sock"))
        monkeypatch.setattr(client, "_request", lambda *_args: {})
        monkeypatch.setattr(agent, "WorkspaceAgentClient", lambda _path: client)

    manager.deploy(Resource(host, "debug", project))

    root = _PATHS.workspace(project, "debug")
    assert directories == [
        root,
        f"{root}/workspace",
        f"{root}/upload",
        f"{root}/control",
        *(f"{root}/cache/{relative}" for relative in _CACHE_PATHS),
    ]
    if invalid_status:
        assert events == ["pull", "paths", "create"]
        failed = manager.operations.list()[0]
        assert failed.status == "failed"
        assert "invalid status" in failed.error
        return
    assert events == [
        "pull",
        "paths",
        "create",
        *(["register", "ready"] if spec.source.type in {"github", "gitlab"} else []),
        "route",
    ]
    assert manager.operations.list() == []


def test_deploy_uses_configured_mounts_alongside_host_volumes(
    manager: ControlPlane, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = config.model_dump()
    volumes = data["project_defaults"]["container"]["volumes"]
    volumes.append(
        {
            "type": "bind",
            "source": "${RESOURCE_DATA}/cache/build",
            "target": "/build-cache",
        }
    )
    data["hosts"]["home"]["container"] = {"volumes": ["/host/file:/opt/file:ro"]}
    manager.config = Config.model_validate(data)
    directories: list[str] = []
    captured: dict[str, object] = {}
    monkeypatch.setattr(lifecycle, "list_workspaces", lambda *_args: [])
    monkeypatch.setattr(lifecycle.container, "pull_image", lambda *_args: None)
    monkeypatch.setattr(host_runtime, "read_environment", lambda *_args: {})
    monkeypatch.setattr(
        host_runtime, "prepare_directories", lambda _route, paths: directories.extend(paths)
    )
    monkeypatch.setattr(
        lifecycle.container,
        "create_container",
        lambda *_args, **kwargs: (captured.update(kwargs), SimpleNamespace(id="container-id"))[-1],
    )

    manager.queue(Resource("home", "debug", "scratch"))
    manager.deploy(Resource("home", "debug", "scratch"))

    root = _PATHS.workspace("scratch", "debug")
    assert manager.operations.list() == []
    assert f"{root}/control" in directories
    assert f"{root}/cache/build" in directories
    assert "/host/file" not in directories
    resolved = {  # type: ignore[union-attr]
        volume.target: volume for volume in captured["spec"].volumes
    }
    assert resolved["/build-cache"].source == f"{root}/cache/build"
    assert resolved["/opt/file"].source == "/host/file"
    assert len(resolved) == 16
    assert manager.transport.socket_forwards == [  # type: ignore[attr-defined]
        ("home", f"{root}/control/agent.sock")
    ]


def test_create_failure_is_retained_as_failed_operation(
    manager: ControlPlane,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager.queue(Resource("home", "debug", "codespace"))
    monkeypatch.setattr(
        lifecycle,
        "list_workspaces",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("Podman unavailable")),
    )

    manager.deploy(Resource("home", "debug", "codespace"))

    assert manager.operations.list()[0].status == "failed"
    assert "Podman unavailable" in (manager.operations.list()[0].error or "")


def test_deletion_check_returns_git_state_without_mutation(
    manager: ControlPlane,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = SimpleNamespace(
        id="container-id",
        name="space-codespace-debug",
        labels=config.workspace_spec("codespace", "home", "debug").labels(),
        attrs={
            "State": {"Status": "running"},
            "Mounts": [
                {"Source": "/deployed/control", "Destination": "/run/codespace-control"},
            ],
        },
    )
    mutations: list[str] = []
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(
        lifecycle.container, "remove_container", lambda *_args: mutations.append("remove")
    )
    manager._token = lambda _provider: (_ for _ in ()).throw(RuntimeError("token must not be read"))

    state = manager.inspect_deletion(Resource("home", "debug", "codespace"))

    assert state.uncommitted is True
    assert mutations == []
    assert manager.transport.closed_tcp == []  # type: ignore[attr-defined]
    assert manager.transport.socket_forwards == [  # type: ignore[attr-defined]
        ("home", "/deployed/control/agent.sock")
    ]


@pytest.mark.parametrize("project", ["codespace", "scratch"])
def test_delete_inspection_never_defaults_an_invalid_agent_response_to_clean(
    manager: ControlPlane,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    project: str,
) -> None:
    running = SimpleNamespace(
        id="container-id",
        name=f"space-{project}-debug",
        labels=config.workspace_spec(project, "home", "debug").labels(),
        attrs={
            "State": {"Status": "running"},
            "Mounts": [
                {"Source": "/deployed/control", "Destination": "/run/codespace-control"},
            ],
        },
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
        assert manager.inspect_deletion(Resource("home", "debug", project)).model_dump() == {
            "unpushed": False,
            "uncommitted": False,
            "detail": [],
        }
        assert requests == []
    else:
        with pytest.raises(agent.AgentError, match="invalid Git state"):
            manager.inspect_deletion(Resource("home", "debug", project))
        assert requests == ["/git-state"]
    assert mutations == []


@pytest.mark.parametrize("revoke_fails", [False, True])
def test_purge_revokes_key_before_data_and_container(
    manager: ControlPlane,
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    revoke_fails: bool,
) -> None:
    events: list[str] = []
    running = SimpleNamespace(
        id="container-id",
        name="space-codespace-debug",
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
    monkeypatch.setattr(ssh, "remove_route", lambda _workspace: events.append("route"))
    if revoke_fails:
        with pytest.raises(RuntimeError, match="provider unavailable"):
            manager.remove(Resource("home", "debug", "codespace"), purge=True)
        assert events == ["revoke"]
        assert manager.transport.closed_tcp == []  # type: ignore[attr-defined]
        return
    manager.remove(Resource("home", "debug", "codespace"), purge=True)

    assert events == ["revoke", "stop", "data", "container", "route"]
    assert manager.transport.closed_tcp == [  # type: ignore[attr-defined]
        ("home", "space-codespace-debug-home")
    ]


def test_stopped_workspace_requires_explicit_delete_without_inspection(
    manager: ControlPlane, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    mutations: list[str] = []
    running = SimpleNamespace(
        id="container-id",
        name="space-personal-debug",
        labels=config.workspace_spec("personal", "home", "debug").labels(),
        attrs={"State": {"Status": "exited"}},
    )
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(
        lifecycle.container, "remove_container", lambda *_args: mutations.append("container")
    )
    with pytest.raises(ResourceConflict, match="cannot be inspected"):
        manager.inspect_deletion(Resource("home", "debug", "personal"))
    assert mutations == []

    assert manager.remove(Resource("home", "debug", "personal"), purge=False) is True
    assert mutations == ["container"]


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
        lambda actual: (calls.append(actual), "agent line\n")[-1],
    )

    assert manager.logs(Resource("home", "debug", "codespace")) == "agent line\n"
    assert calls == [running]


@pytest.mark.parametrize("encrypted", [False, True])
def test_workspace_container_uses_fixed_ssh_listener_and_configured_mounts(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
    encrypted: bool,
) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["encrypted"] = encrypted
    data["secrets"]["codespace_workspace_key"] = "test-key"
    configured_secrets = [{"source": "atuin_db_uri", "mode": 0o400}]
    if encrypted:
        configured_secrets.append(
            {
                "source": "codespace_workspace_key",
                "uid": "5230",
                "gid": "5230",
                "mode": 0o400,
            }
        )
    data["projects"]["codespace"]["container"] = {
        "secrets": configured_secrets,
        "volumes": [
            {
                "source": "${RESOURCE_DATA}/workspace",
                "target": "/workspace.enc" if encrypted else "/workspace",
                "type": "bind",
            }
        ],
    }
    data["projects"]["codespace"]["source"]["args"] = ["--depth=1", "--single-branch"]
    spec = Config.model_validate(data).workspace_spec("codespace", "home", "debug")
    original_container = spec.container.model_dump()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        lifecycle.container,
        "create_container",
        lambda *_args, **kwargs: (captured.update(kwargs), SimpleNamespace())[-1],
    )

    lifecycle.create_container(
        SimpleNamespace(),  # type: ignore[arg-type]
        spec,
        _PATHS.workspace("codespace", "debug"),
        {"HTTP_PROXY": "proxy"},
    )

    assert captured["name"] == "space-codespace-debug"
    environment = captured["spec"].environment  # type: ignore[union-attr]
    assert isinstance(environment, dict)
    assert environment["CODESPACE_SOURCE_TYPE"] == "github"
    assert environment["CODESPACE_CHECKOUT_PATH"] == "/workspace/codespace"
    assert environment["CODESPACE_OPEN_PATH"] == "/workspace/codespace"
    assert environment["CODESPACE_ENCRYPTED"] == str(encrypted).lower()
    assert "CODESPACE_ENCRYPTED_PATH" not in environment
    assert environment["CODESPACE_CLONE_URL"] == "git@github.com:curoky/codespace.git"
    assert environment["CODESPACE_GIT_ARGS"] == '["--depth=1", "--single-branch"]'
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
    expected_mounts = [
        {
            "type": "bind",
            "source": "/etc/krb5.conf",
            "target": "/etc/krb5.conf",
            "read_only": True,
        },
        {
            "type": "bind",
            "source": "/home/x/codespace/workspaces/codespace/debug/workspace",
            "target": "/workspace.enc" if encrypted else "/workspace",
            "read_only": False,
        },
        {
            "type": "bind",
            "source": "/home/x/codespace/workspaces/codespace/debug/upload",
            "target": "/upload",
            "read_only": False,
        },
        {
            "type": "bind",
            "source": "/home/x/codespace/workspaces/codespace/debug/control",
            "target": "/run/codespace-control",
            "read_only": False,
        },
        *(
            {
                "type": "bind",
                "source": f"/home/x/codespace/workspaces/codespace/debug/cache/{relative}",
                "target": f"/home/x/{relative}",
                "read_only": False,
            }
            for relative in _CACHE_PATHS
        ),
    ]
    assert [volume.mount() for volume in captured["spec"].volumes] == expected_mounts  # type: ignore[union-attr]
    assert [port.target for port in captured["spec"].ports] == [22]  # type: ignore[union-attr]
    assert spec.container.model_dump() == original_container


def test_encrypted_workspace_uses_configured_compose_secret(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = config.model_dump()
    data["projects"]["codespace"]["encrypted"] = True
    data["projects"]["codespace"]["container"] = {
        "volumes": ["${RESOURCE_DATA}/workspace:/workspace.enc"],
        "secrets": [
            {
                "source": "codespace_workspace_key",
                "uid": "5230",
                "gid": "5230",
                "mode": 0o400,
            }
        ],
    }
    data["secrets"]["codespace_workspace_key"] = "test-key"
    spec = Config.model_validate(data).workspace_spec("codespace", "home", "debug")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        lifecycle.container,
        "create_container",
        lambda *_args, **kwargs: (captured.update(kwargs), SimpleNamespace())[-1],
    )

    lifecycle.create_container(
        SimpleNamespace(),  # type: ignore[arg-type]
        spec,
        _PATHS.workspace("codespace", "debug"),
        {},
    )

    runtime_spec = captured["spec"]
    assert runtime_spec.environment["CODESPACE_ENCRYPTED"] == "true"  # type: ignore[union-attr]
    assert runtime_spec.environment["CODESPACE_GIT_ARGS"] == "[]"  # type: ignore[union-attr]
    assert captured["labels"]["codespace.encrypted"] == "true"  # type: ignore[index]
    assert spec.container.secrets == runtime_spec.secrets  # type: ignore[union-attr]
    assert runtime_spec.secrets[0].model_dump() == {  # type: ignore[union-attr]
        "source": "codespace_workspace_key",
        "target": None,
        "uid": "5230",
        "gid": "5230",
        "mode": 0o400,
    }


def test_delete_uses_deployed_source_after_config_changes(
    manager: ControlPlane, config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    running = SimpleNamespace(
        id="container-id",
        name="space-codespace-debug",
        labels=config.workspace_spec("codespace", "home", "debug").labels(),
        attrs={
            "State": {"Status": "running"},
            "Mounts": [
                {"Source": "/deployed/control", "Destination": "/run/codespace-control"},
            ],
        },
    )
    data = config.model_dump()
    data["projects"]["codespace"]["source"] = {"type": "empty"}
    manager.config = Config.model_validate(data)
    revoked: list[tuple[str, ...]] = []
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: running)
    monkeypatch.setattr(provider, "revoke", lambda *args: revoked.append(args))
    monkeypatch.setattr(lifecycle.container, "remove_container", lambda _container: None)

    assert manager.inspect_deletion(Resource("home", "debug", "codespace")).uncommitted
    manager.remove(Resource("home", "debug", "codespace"), purge=False)

    assert revoked == [("github", "token", "curoky/codespace", "space:codespace/debug@home")]


@pytest.fixture
def tunnel_container(
    manager: ControlPlane, config: Config, monkeypatch: pytest.MonkeyPatch
) -> SimpleNamespace:
    running = SimpleNamespace(
        id="deployed-container",
        name="space-codespace-debug",
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
    manager: ControlPlane,
    tunnel_container: SimpleNamespace,
    port: int,
) -> None:
    actual = inventory.read_workspace(tunnel_container, "home")

    assert manager.open_tunnel(Resource("home", "debug", "codespace"), port) == 49123
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
    manager: ControlPlane, tunnel_container: SimpleNamespace, status: str
) -> None:
    tunnel_container.attrs["State"]["Status"] = status

    with pytest.raises(ResourceConflict, match="is not running"):
        manager.open_tunnel(Resource("home", "debug", "codespace"), 8005)
    assert manager.transport.tcp_forwards == []  # type: ignore[attr-defined]


def test_tunnel_rejects_unconfigured_port(
    manager: ControlPlane, tunnel_container: SimpleNamespace
) -> None:
    with pytest.raises(ResourceNotFound, match="not configured"):
        manager.open_tunnel(Resource("home", "debug", "codespace"), 22)
    assert manager.transport.tcp_forwards == []  # type: ignore[attr-defined]


def test_tunnel_rejects_missing_workspace(
    manager: ControlPlane, tunnel_container: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(lifecycle.container, "find_container", lambda *_args, **_kwargs: None)
    with pytest.raises(ResourceNotFound, match="not found"):
        manager.open_tunnel(Resource("home", "debug", "codespace"), 8005)
    assert manager.transport.tcp_forwards == []  # type: ignore[attr-defined]
