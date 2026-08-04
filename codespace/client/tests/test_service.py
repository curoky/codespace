"""Tests for local lifecycle orchestration and fail-closed rollback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codespace.client import container as containers
from codespace.client import inventory, provider, ssh, workspace
from codespace.client.config import Config
from codespace.client.models import (
    Environment,
    EnvironmentSpec,
    RepoGitState,
    environment_id,
    ssh_port,
)
from codespace.client.service import CodespaceService, describe_error
from codespace.client.transport import SSHRoute


class FakeTransport:
    def __init__(self, clients: dict[str, object]) -> None:
        self.clients = clients
        self.closed = False

    def client(self, host: str) -> object:
        client = self.clients[host]
        if isinstance(client, Exception):
            raise client
        return client

    def ssh_route(self, host: str) -> SSHRoute:
        return SSHRoute(host=host)

    def close(self) -> None:
        self.closed = True


def _environment(
    *,
    host: str = "home",
    project: str = "devspace",
    instance: str = "debug",
) -> Environment:
    identity = environment_id(host, project, instance)
    provider_name = "github" if host == "home" else "gitlab"
    repo = "curoky/devspace" if host == "home" else "group/service-api"
    return Environment(
        id=identity,
        host=host,
        project=project,
        instance=instance,
        type="repo",
        repo=repo,
        provider=provider_name,
        image="image:latest",
        platform="native",
        ssh_port=ssh_port(identity),
        container_id="container-id",
        status="running",
    )


@pytest.fixture
def service(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> CodespaceService:
    monkeypatch.setattr(ssh, "initialize", lambda hosts: None)
    monkeypatch.setattr(ssh, "remote_workspace_root", lambda route: "/home/x/codespace")
    return CodespaceService(
        config,
        transport=FakeTransport({"home": object(), "office": object()}),  # type: ignore[arg-type]
    )


def _queue_with_token(service: CodespaceService) -> None:
    service.set_token("github", "token")
    service.queue_create("devspace", "debug")


def test_service_seeds_tokens_from_config(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ssh, "initialize", lambda hosts: None)
    seeded = Config.model_validate({**config.model_dump(), "tokens": {"github": "ghp_example"}})
    service = CodespaceService(
        seeded,
        transport=FakeTransport({"home": object(), "office": object()}),  # type: ignore[arg-type]
    )

    assert service.token_status() == {"github": True, "gitlab": False}


def test_dashboard_isolates_offline_host_and_rewrites_successful_host(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ssh, "initialize", lambda hosts: None)
    writes: list[tuple[str, list[Environment]]] = []
    monkeypatch.setattr(
        ssh,
        "write_host",
        lambda host, envs, route: writes.append((host, envs)),
    )
    home_client = object()
    transport = FakeTransport({"home": home_client, "office": RuntimeError("ssh down")})
    service = CodespaceService(config, transport=transport)  # type: ignore[arg-type]
    monkeypatch.setattr(
        inventory,
        "list_inventory",
        lambda client, host, cfg: inventory.Inventory([_environment()], []),
    )

    dashboard = service.dashboard()

    assert [host.status for host in dashboard.hosts] == ["online", "offline"]
    assert dashboard.hosts[1].error == "RuntimeError: ssh down"
    assert [environment.id for environment in dashboard.environments] == [
        "codespace-home-devspace-debug"
    ]
    assert writes == [("home", [_environment()])]


def test_dashboard_keeps_failed_operation_when_container_was_retained(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _queue_with_token(service)
    service.operations.update(
        "devspace",
        "debug",
        status="failed",
        stage="failed",
        error="rollback stopped: provider unavailable",
    )
    monkeypatch.setattr(
        inventory,
        "list_inventory",
        lambda client, host, cfg: (
            inventory.Inventory([_environment()], [])
            if host == "home"
            else inventory.Inventory([], [])
        ),
    )
    monkeypatch.setattr(ssh, "write_host", lambda host, environments, route: None)

    dashboard = service.dashboard()

    assert len(dashboard.environments) == 1
    assert len(dashboard.operations) == 1
    assert dashboard.operations[0].status == "failed"


def test_create_runs_all_stages_in_order(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _queue_with_token(service)
    service.config.hosts["home"].environment = ["HTTP_PROXY"]
    events: list[str] = []
    specs: list[EnvironmentSpec] = []
    inherited_environments: list[dict[str, str]] = []
    container = SimpleNamespace(id="container-id")
    inventories = iter(
        [
            inventory.Inventory([], []),
            inventory.Inventory([_environment()], []),
        ]
    )
    monkeypatch.setattr(inventory, "list_inventory", lambda *args: next(inventories))
    monkeypatch.setattr(
        ssh,
        "read_host_environment",
        lambda route, names: (
            events.append("environment") or {"HTTP_PROXY": "http://host-proxy:3128"}
        ),
    )
    monkeypatch.setattr(
        workspace,
        "generate_deploy_keypair",
        lambda: (
            events.append("keygen")
            or workspace.DeployKeypair(private_key="PRIVATE", public_key="PUBLIC")
        ),
    )
    pulls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        containers,
        "pull_image",
        lambda _client, image, platform: (
            pulls.append((image, platform)),
            events.append("pull"),
        ),
    )
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: events.append("workspace"))

    def create_container(
        _client: object,
        spec: EnvironmentSpec,
        _workspace_root: str,
        host_environment: dict[str, str],
    ) -> object:
        specs.append(spec)
        inherited_environments.append(host_environment)
        events.append("create")
        return container

    monkeypatch.setattr(
        containers,
        "create_container",
        create_container,
    )
    monkeypatch.setattr(
        workspace, "inject_deploy_key", lambda *args, **kwargs: events.append("inject")
    )
    monkeypatch.setattr(ssh, "probe", lambda *args: events.append("probe"))
    monkeypatch.setattr(provider, "register", lambda *args: events.append("register"))
    monkeypatch.setattr(workspace, "clone_repo", lambda *args: events.append("clone"))
    monkeypatch.setattr(ssh, "write_host", lambda *args: events.append("projection"))

    service.create("devspace", "debug")

    assert events == [
        "environment",
        "keygen",
        "pull",
        "workspace",
        "create",
        "inject",
        "probe",
        "register",
        "clone",
        "projection",
    ]
    assert pulls == [(service.config.default_image, "linux/arm64")]
    assert specs[0].project.platform == "linux/arm64"
    assert specs[0].container.network_mode == "host"
    assert specs[0].published_ports == ()
    assert inherited_environments == [{"HTTP_PROXY": "http://host-proxy:3128"}]
    assert service.operations.list() == []


def test_create_on_podman_machine_host_uses_bridge_and_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ssh, "initialize", lambda hosts: None)
    monkeypatch.setattr(ssh, "remote_workspace_root", lambda route: "/home/x/codespace")
    config = Config.model_validate(
        {
            "default_image": "img:latest",
            "container": {
                "network_mode": "bridge",
                "cap_add": ["NET_RAW", "SYS_ADMIN"],
                "security_opt": ["disable", "seccomp=unconfined"],
                "pids_limit": -1,
                "ulimits": {"memlock": {"soft": -1, "hard": -1}},
            },
            "hosts": {
                "local": {
                    "type": "podman-machine",
                    "machine": "podman-machine-default",
                },
            },
            "projects": {
                "devspace": {
                    "host": "local",
                    "provider": "github",
                    "repo": "curoky/devspace",
                    "published_ports": ["8080", "3000:5000"],
                }
            },
        }
    )
    service = CodespaceService(
        config,
        transport=FakeTransport({"local": object()}),  # type: ignore[arg-type]
    )
    service.set_token("github", "token")
    service.queue_create("devspace", "debug")

    specs: list[EnvironmentSpec] = []
    container = SimpleNamespace(id="container-id")
    environment = _environment(host="local")
    inventories = iter([inventory.Inventory([], []), inventory.Inventory([environment], [])])
    monkeypatch.setattr(inventory, "list_inventory", lambda *args: next(inventories))
    monkeypatch.setattr(
        workspace,
        "generate_deploy_keypair",
        lambda: workspace.DeployKeypair(private_key="PRIVATE", public_key="PUBLIC"),
    )
    monkeypatch.setattr(containers, "pull_image", lambda *args: None)
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: None)
    monkeypatch.setattr(
        containers,
        "create_container",
        lambda _client, spec, _root, _environment: (specs.append(spec), container)[-1],
    )
    monkeypatch.setattr(workspace, "inject_deploy_key", lambda *args, **kwargs: None)
    monkeypatch.setattr(ssh, "probe", lambda *args: None)
    monkeypatch.setattr(provider, "register", lambda *args: None)
    monkeypatch.setattr(workspace, "clone_repo", lambda *args: None)
    monkeypatch.setattr(ssh, "write_host", lambda *args: None)

    service.create("devspace", "debug")

    assert specs[0].container.network_mode == "bridge"
    assert specs[0].published_ports == ((8080, 8080), (3000, 5000))
    assert service.operations.list() == []


def test_create_blank_project_skips_repo_stages(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.queue_create("scratch", "debug")
    events: list[str] = []
    container = SimpleNamespace(id="container-id")
    scratch_env = _environment(project="scratch")
    inventories = iter(
        [
            inventory.Inventory([], []),
            inventory.Inventory([scratch_env], []),
        ]
    )
    monkeypatch.setattr(inventory, "list_inventory", lambda *args: next(inventories))
    monkeypatch.setattr(
        workspace,
        "generate_deploy_keypair",
        lambda: events.append("keygen") or workspace.DeployKeypair("PRIVATE", "PUBLIC"),
    )
    monkeypatch.setattr(containers, "pull_image", lambda *args: events.append("pull"))
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: events.append("workspace"))
    monkeypatch.setattr(
        containers,
        "create_container",
        lambda *args, **kwargs: (events.append("create"), container)[-1],
    )
    monkeypatch.setattr(
        workspace, "inject_deploy_key", lambda *args, **kwargs: events.append("inject")
    )
    monkeypatch.setattr(ssh, "probe", lambda *args: events.append("probe"))
    monkeypatch.setattr(provider, "register", lambda *args: events.append("register"))
    monkeypatch.setattr(workspace, "clone_repo", lambda *args: events.append("clone"))
    monkeypatch.setattr(workspace, "prepare_open_path", lambda *args: events.append("open_path"))
    monkeypatch.setattr(ssh, "write_host", lambda *args: events.append("projection"))

    service.create("scratch", "debug")

    assert "keygen" not in events
    assert "register" not in events
    assert "clone" not in events
    assert events == [
        "pull",
        "workspace",
        "create",
        "probe",
        "open_path",
        "projection",
    ]
    assert service.operations.list() == []


def test_queue_create_blank_project_needs_no_token(service: CodespaceService) -> None:
    operation = service.queue_create("scratch", "debug")

    assert operation.project == "scratch"


def test_create_rejects_duplicate_before_generating_keys(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _queue_with_token(service)
    monkeypatch.setattr(
        inventory,
        "list_inventory",
        lambda *args: inventory.Inventory([_environment()], []),
    )
    generated: list[bool] = []
    monkeypatch.setattr(
        workspace,
        "generate_deploy_keypair",
        lambda: generated.append(True),
    )

    service.create("devspace", "debug")

    operation = service.operations.list()[0]
    assert operation.status == "failed"
    assert "already exists" in (operation.error or "")
    assert generated == []


def test_create_rejects_deterministic_port_collision(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _queue_with_token(service)
    collision = _environment(instance="other")
    collision.ssh_port = ssh_port("codespace-home-devspace-debug")
    monkeypatch.setattr(
        inventory,
        "list_inventory",
        lambda *args: inventory.Inventory([collision], []),
    )

    service.create("devspace", "debug")

    error = service.operations.list()[0].error or ""
    assert "SSH port collision" in error
    assert "choose a different instance name" in error


def test_failure_before_register_removes_container_but_keeps_workspace(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _queue_with_token(service)
    container = SimpleNamespace(id="container-id")
    removed: list[object] = []
    monkeypatch.setattr(
        inventory,
        "list_inventory",
        lambda *args: inventory.Inventory([], []),
    )
    monkeypatch.setattr(
        workspace,
        "generate_deploy_keypair",
        lambda: workspace.DeployKeypair(private_key="PRIVATE", public_key="PUBLIC"),
    )
    monkeypatch.setattr(containers, "pull_image", lambda *args: None)
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: None)
    monkeypatch.setattr(containers, "create_container", lambda *args, **kwargs: container)
    monkeypatch.setattr(workspace, "inject_deploy_key", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ssh,
        "probe",
        lambda *args: (_ for _ in ()).throw(RuntimeError("no ssh")),
    )
    monkeypatch.setattr(inventory, "find_container", lambda *args: container)
    monkeypatch.setattr(containers, "remove_container", lambda item: removed.append(item))
    monkeypatch.setattr(provider, "revoke", lambda *args: pytest.fail("must not revoke"))

    service.create("devspace", "debug")

    assert removed == [container]
    assert service.operations.list()[0].error == "RuntimeError: no ssh"


def test_container_run_failure_still_attempts_deterministic_cleanup(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _queue_with_token(service)
    container = SimpleNamespace(id="container-id")
    removed: list[object] = []
    monkeypatch.setattr(
        inventory,
        "list_inventory",
        lambda *args: inventory.Inventory([], []),
    )
    monkeypatch.setattr(
        workspace,
        "generate_deploy_keypair",
        lambda: workspace.DeployKeypair(private_key="PRIVATE", public_key="PUBLIC"),
    )
    monkeypatch.setattr(containers, "pull_image", lambda *args: None)
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: None)
    monkeypatch.setattr(
        containers,
        "create_container",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("wait failed")),
    )
    monkeypatch.setattr(inventory, "find_container", lambda *args: container)
    monkeypatch.setattr(containers, "remove_container", lambda item: removed.append(item))

    service.create("devspace", "debug")

    assert removed == [container]
    assert service.operations.list()[0].error == "RuntimeError: wait failed"


def test_failure_after_register_revokes_then_removes_container(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _queue_with_token(service)
    events: list[str] = []
    container = SimpleNamespace(id="container-id")
    monkeypatch.setattr(inventory, "list_inventory", lambda *args: inventory.Inventory([], []))
    monkeypatch.setattr(
        workspace,
        "generate_deploy_keypair",
        lambda: workspace.DeployKeypair(private_key="PRIVATE", public_key="PUBLIC"),
    )
    monkeypatch.setattr(containers, "pull_image", lambda *args: None)
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: None)
    monkeypatch.setattr(containers, "create_container", lambda *args, **kwargs: container)
    monkeypatch.setattr(workspace, "inject_deploy_key", lambda *args, **kwargs: None)
    monkeypatch.setattr(ssh, "probe", lambda *args: None)
    monkeypatch.setattr(provider, "register", lambda *args: events.append("register"))
    monkeypatch.setattr(
        workspace,
        "clone_repo",
        lambda *args: (_ for _ in ()).throw(RuntimeError("clone failed")),
    )
    monkeypatch.setattr(inventory, "find_container", lambda *args: container)
    monkeypatch.setattr(provider, "revoke", lambda *args: events.append("revoke"))
    monkeypatch.setattr(containers, "remove_container", lambda item: events.append("remove"))

    service.create("devspace", "debug")

    assert events == ["register", "revoke", "remove"]


def test_revoke_failure_after_register_retains_container(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _queue_with_token(service)
    stopped: list[int] = []
    container = SimpleNamespace(
        id="container-id",
        stop=lambda *, timeout: stopped.append(timeout),
    )
    removed: list[object] = []
    monkeypatch.setattr(inventory, "list_inventory", lambda *args: inventory.Inventory([], []))
    monkeypatch.setattr(
        workspace,
        "generate_deploy_keypair",
        lambda: workspace.DeployKeypair(private_key="PRIVATE", public_key="PUBLIC"),
    )
    monkeypatch.setattr(containers, "pull_image", lambda *args: None)
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: None)
    monkeypatch.setattr(containers, "create_container", lambda *args, **kwargs: container)
    monkeypatch.setattr(workspace, "inject_deploy_key", lambda *args, **kwargs: None)
    monkeypatch.setattr(ssh, "probe", lambda *args: None)
    monkeypatch.setattr(provider, "register", lambda *args: None)
    monkeypatch.setattr(
        workspace,
        "clone_repo",
        lambda *args: (_ for _ in ()).throw(RuntimeError("clone failed")),
    )
    monkeypatch.setattr(
        provider,
        "revoke",
        lambda *args: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )
    monkeypatch.setattr(inventory, "find_container", lambda *args: container)
    monkeypatch.setattr(containers, "remove_container", lambda item: removed.append(item))

    service.create("devspace", "debug")

    assert removed == []
    assert stopped == [10]
    assert "rollback stopped: RuntimeError: provider unavailable" in (
        service.operations.list()[0].error or ""
    )


def test_delete_requires_token_before_remote_mutation(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    touched: list[bool] = []
    monkeypatch.setattr(inventory, "list_inventory", lambda *args: touched.append(True))

    with pytest.raises(RuntimeError, match="token is not set"):
        service.delete("devspace", "debug", purge=False)

    assert touched == []


@pytest.mark.parametrize(
    ("purge", "expected"),
    [
        (False, ["revoke", "remove", "projection"]),
        (True, ["revoke", "purge", "remove", "projection"]),
    ],
)
def test_delete_revokes_before_container_and_workspace_mutation(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
    purge: bool,
    expected: list[str],
) -> None:
    service.set_token("github", "token")
    container = object()
    events: list[str] = []
    inventories = iter(
        [
            inventory.Inventory([_environment()], []),
            inventory.Inventory([], []),
        ]
    )
    monkeypatch.setattr(inventory, "list_inventory", lambda *args: next(inventories))
    monkeypatch.setattr(inventory, "find_container", lambda *args: container)
    monkeypatch.setattr(workspace, "repo_git_state", lambda *args: RepoGitState())
    monkeypatch.setattr(provider, "revoke", lambda *args: events.append("revoke"))
    monkeypatch.setattr(containers, "purge_workspace", lambda *args: events.append("purge"))
    monkeypatch.setattr(containers, "remove_container", lambda item: events.append("remove"))
    monkeypatch.setattr(ssh, "write_host", lambda *args: events.append("projection"))

    service.delete("devspace", "debug", purge=purge, force=True)

    assert events == expected


def test_delete_revoke_failure_refuses_all_mutation(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.set_token("github", "token")
    container = object()
    mutations: list[str] = []
    monkeypatch.setattr(
        inventory,
        "list_inventory",
        lambda *args: inventory.Inventory([_environment()], []),
    )
    monkeypatch.setattr(inventory, "find_container", lambda *args: container)
    monkeypatch.setattr(workspace, "repo_git_state", lambda *args: RepoGitState())
    monkeypatch.setattr(
        provider,
        "revoke",
        lambda *args: (_ for _ in ()).throw(RuntimeError("denied")),
    )
    monkeypatch.setattr(containers, "purge_workspace", lambda *args: mutations.append("purge"))
    monkeypatch.setattr(containers, "remove_container", lambda item: mutations.append("remove"))

    with pytest.raises(RuntimeError, match="denied"):
        service.delete("devspace", "debug", purge=True, force=True)

    assert mutations == []


def test_delete_without_force_inspects_and_skips_mutation(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.set_token("github", "token")
    container = object()
    mutations: list[str] = []
    monkeypatch.setattr(
        inventory,
        "list_inventory",
        lambda *args: inventory.Inventory([_environment()], []),
    )
    monkeypatch.setattr(inventory, "find_container", lambda *args: container)
    monkeypatch.setattr(
        workspace,
        "repo_git_state",
        lambda *args: RepoGitState(unpushed=True, detail=["abc add feature"]),
    )
    monkeypatch.setattr(provider, "revoke", lambda *args: mutations.append("revoke"))
    monkeypatch.setattr(containers, "purge_workspace", lambda *args: mutations.append("purge"))
    monkeypatch.setattr(containers, "remove_container", lambda item: mutations.append("remove"))

    state = service.delete("devspace", "debug", purge=True, force=False)

    assert state.unpushed is True
    assert state.detail == ["abc add feature"]
    assert mutations == []


def test_delete_force_skips_git_check_and_deletes(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.set_token("github", "token")
    container = object()
    events: list[str] = []
    inventories = iter(
        [
            inventory.Inventory([_environment()], []),
            inventory.Inventory([], []),
        ]
    )
    monkeypatch.setattr(inventory, "list_inventory", lambda *args: next(inventories))
    monkeypatch.setattr(inventory, "find_container", lambda *args: container)

    def _fail_git_state(*_args: object) -> RepoGitState:
        raise AssertionError("repo_git_state must not run when force=True")

    monkeypatch.setattr(workspace, "repo_git_state", _fail_git_state)
    monkeypatch.setattr(provider, "revoke", lambda *args: events.append("revoke"))
    monkeypatch.setattr(containers, "remove_container", lambda item: events.append("remove"))
    monkeypatch.setattr(ssh, "write_host", lambda *args: events.append("projection"))

    service.delete("devspace", "debug", purge=False, force=True)

    assert events == ["revoke", "remove", "projection"]


def test_describe_error_unwraps_cause_chain() -> None:
    cause = TimeoutError("timed out")
    try:
        try:
            raise cause
        except TimeoutError as inner:
            raise RuntimeError("GET operation failed") from inner
    except RuntimeError as exc:
        message = describe_error(exc)

    assert message == "RuntimeError: GET operation failed <- TimeoutError: timed out"


def test_describe_error_uses_implicit_context() -> None:
    try:
        try:
            raise ValueError("bad socket")
        except ValueError:
            raise RuntimeError("wrapper")  # noqa: B904 — exercising implicit __context__
    except RuntimeError as exc:
        message = describe_error(exc)

    assert message == "RuntimeError: wrapper <- ValueError: bad socket"


def test_describe_error_handles_empty_message() -> None:
    assert describe_error(RuntimeError()) == "RuntimeError"
