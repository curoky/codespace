"""Tests for local lifecycle orchestration and fail-closed rollback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from codespace.client import provider, runtime, ssh
from codespace.client.config import Config
from codespace.client.models import Environment, environment_id, ssh_port
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
    monkeypatch.setattr(ssh, "remote_workspace_root", lambda route: "/home/x/codespace2")
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
        runtime,
        "list_inventory",
        lambda client, host, cfg: runtime.Inventory([_environment()], []),
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
        runtime,
        "list_inventory",
        lambda client, host, cfg: (
            runtime.Inventory([_environment()], []) if host == "home" else runtime.Inventory([], [])
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
    events: list[str] = []
    platforms: list[str | None] = []
    container = SimpleNamespace(id="container-id")
    inventories = iter(
        [
            runtime.Inventory([], []),
            runtime.Inventory([_environment()], []),
        ]
    )
    monkeypatch.setattr(runtime, "list_inventory", lambda *args: next(inventories))
    monkeypatch.setattr(ssh, "ensure_login_key", lambda: events.append("login") or "LOGIN")
    monkeypatch.setattr(
        runtime,
        "generate_deploy_keypair",
        lambda: (
            events.append("keygen")
            or runtime.DeployKeypair(private_key="PRIVATE", public_key="PUBLIC")
        ),
    )
    pulls: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        runtime,
        "pull_image",
        lambda _client, image, platform: (
            pulls.append((image, platform)),
            events.append("pull"),
        ),
    )
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: events.append("workspace"))
    monkeypatch.setattr(
        runtime,
        "create_container",
        lambda *args, **kwargs: (
            platforms.append(kwargs["platform"]),
            events.append("create"),
            container,
        )[-1],
    )
    monkeypatch.setattr(
        runtime, "inject_credentials", lambda *args, **kwargs: events.append("inject")
    )
    monkeypatch.setattr(ssh, "probe", lambda environment, route: events.append("probe"))
    monkeypatch.setattr(provider, "register", lambda *args: events.append("register"))
    monkeypatch.setattr(runtime, "clone_repo", lambda *args: events.append("clone"))
    monkeypatch.setattr(ssh, "write_host", lambda *args: events.append("projection"))

    service.create("devspace", "debug")

    assert events == [
        "login",
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
    assert platforms == ["linux/arm64"]
    assert service.operations.list() == []


def test_create_rejects_duplicate_before_generating_keys(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _queue_with_token(service)
    monkeypatch.setattr(
        runtime,
        "list_inventory",
        lambda *args: runtime.Inventory([_environment()], []),
    )
    generated: list[bool] = []
    monkeypatch.setattr(
        runtime,
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
        runtime,
        "list_inventory",
        lambda *args: runtime.Inventory([collision], []),
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
        runtime,
        "list_inventory",
        lambda *args: runtime.Inventory([], []),
    )
    monkeypatch.setattr(ssh, "ensure_login_key", lambda: "LOGIN")
    monkeypatch.setattr(
        runtime,
        "generate_deploy_keypair",
        lambda: runtime.DeployKeypair(private_key="PRIVATE", public_key="PUBLIC"),
    )
    monkeypatch.setattr(runtime, "pull_image", lambda *args: None)
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: None)
    monkeypatch.setattr(runtime, "create_container", lambda *args, **kwargs: container)
    monkeypatch.setattr(runtime, "inject_credentials", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        ssh,
        "probe",
        lambda environment, route: (_ for _ in ()).throw(RuntimeError("no ssh")),
    )
    monkeypatch.setattr(runtime, "find_container", lambda *args: container)
    monkeypatch.setattr(runtime, "remove_container", lambda item: removed.append(item))
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
        runtime,
        "list_inventory",
        lambda *args: runtime.Inventory([], []),
    )
    monkeypatch.setattr(ssh, "ensure_login_key", lambda: "LOGIN")
    monkeypatch.setattr(
        runtime,
        "generate_deploy_keypair",
        lambda: runtime.DeployKeypair(private_key="PRIVATE", public_key="PUBLIC"),
    )
    monkeypatch.setattr(runtime, "pull_image", lambda *args: None)
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: None)
    monkeypatch.setattr(
        runtime,
        "create_container",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("wait failed")),
    )
    monkeypatch.setattr(runtime, "find_container", lambda *args: container)
    monkeypatch.setattr(runtime, "remove_container", lambda item: removed.append(item))

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
    monkeypatch.setattr(runtime, "list_inventory", lambda *args: runtime.Inventory([], []))
    monkeypatch.setattr(ssh, "ensure_login_key", lambda: "LOGIN")
    monkeypatch.setattr(
        runtime,
        "generate_deploy_keypair",
        lambda: runtime.DeployKeypair(private_key="PRIVATE", public_key="PUBLIC"),
    )
    monkeypatch.setattr(runtime, "pull_image", lambda *args: None)
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: None)
    monkeypatch.setattr(runtime, "create_container", lambda *args, **kwargs: container)
    monkeypatch.setattr(runtime, "inject_credentials", lambda *args, **kwargs: None)
    monkeypatch.setattr(ssh, "probe", lambda environment, route: None)
    monkeypatch.setattr(provider, "register", lambda *args: events.append("register"))
    monkeypatch.setattr(
        runtime,
        "clone_repo",
        lambda *args: (_ for _ in ()).throw(RuntimeError("clone failed")),
    )
    monkeypatch.setattr(runtime, "find_container", lambda *args: container)
    monkeypatch.setattr(provider, "revoke", lambda *args: events.append("revoke"))
    monkeypatch.setattr(runtime, "remove_container", lambda item: events.append("remove"))

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
    monkeypatch.setattr(runtime, "list_inventory", lambda *args: runtime.Inventory([], []))
    monkeypatch.setattr(ssh, "ensure_login_key", lambda: "LOGIN")
    monkeypatch.setattr(
        runtime,
        "generate_deploy_keypair",
        lambda: runtime.DeployKeypair(private_key="PRIVATE", public_key="PUBLIC"),
    )
    monkeypatch.setattr(runtime, "pull_image", lambda *args: None)
    monkeypatch.setattr(ssh, "prepare_workspace", lambda *args: None)
    monkeypatch.setattr(runtime, "create_container", lambda *args, **kwargs: container)
    monkeypatch.setattr(runtime, "inject_credentials", lambda *args, **kwargs: None)
    monkeypatch.setattr(ssh, "probe", lambda environment, route: None)
    monkeypatch.setattr(provider, "register", lambda *args: None)
    monkeypatch.setattr(
        runtime,
        "clone_repo",
        lambda *args: (_ for _ in ()).throw(RuntimeError("clone failed")),
    )
    monkeypatch.setattr(
        provider,
        "revoke",
        lambda *args: (_ for _ in ()).throw(RuntimeError("provider unavailable")),
    )
    monkeypatch.setattr(runtime, "find_container", lambda *args: container)
    monkeypatch.setattr(runtime, "remove_container", lambda item: removed.append(item))

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
    monkeypatch.setattr(runtime, "list_inventory", lambda *args: touched.append(True))

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
            runtime.Inventory([_environment()], []),
            runtime.Inventory([], []),
        ]
    )
    monkeypatch.setattr(runtime, "list_inventory", lambda *args: next(inventories))
    monkeypatch.setattr(runtime, "find_container", lambda *args: container)
    monkeypatch.setattr(runtime, "read_environment", lambda *args: _environment())
    monkeypatch.setattr(provider, "revoke", lambda *args: events.append("revoke"))
    monkeypatch.setattr(runtime, "purge_workspace", lambda *args: events.append("purge"))
    monkeypatch.setattr(runtime, "remove_container", lambda item: events.append("remove"))
    monkeypatch.setattr(ssh, "write_host", lambda *args: events.append("projection"))

    service.delete("devspace", "debug", purge=purge)

    assert events == expected


def test_delete_revoke_failure_refuses_all_mutation(
    service: CodespaceService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service.set_token("github", "token")
    container = object()
    mutations: list[str] = []
    monkeypatch.setattr(
        runtime,
        "list_inventory",
        lambda *args: runtime.Inventory([_environment()], []),
    )
    monkeypatch.setattr(runtime, "find_container", lambda *args: container)
    monkeypatch.setattr(
        provider,
        "revoke",
        lambda *args: (_ for _ in ()).throw(RuntimeError("denied")),
    )
    monkeypatch.setattr(runtime, "purge_workspace", lambda *args: mutations.append("purge"))
    monkeypatch.setattr(runtime, "remove_container", lambda item: mutations.append("remove"))

    with pytest.raises(RuntimeError, match="denied"):
        service.delete("devspace", "debug", purge=True)

    assert mutations == []


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
