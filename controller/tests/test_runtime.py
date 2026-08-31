"""Tests for Podman inventory, fixed runtime parameters and container helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Protocol

import pytest
from podman.errors import PodmanError

from controller import container as container_runtime
from controller import deployment as deployment_ops
from controller import inventory, workspace
from controller.config import Config, EnvironmentSpec
from controller.models import (
    LABEL_DEPLOYMENT,
    LABEL_DEPLOYMENT_ID,
    LABEL_IMAGE,
    LABEL_INSTANCE,
    LABEL_MANAGED,
    LABEL_PLATFORM,
    LABEL_PROVIDER,
    LABEL_REPO,
    LABEL_SSH_PORT,
    LABEL_TYPE,
    LABEL_WORKSPACE,
    MANDATORY_LABELS,
    Deployment,
    DeploymentOperation,
    Environment,
    HostDataPaths,
    deployment_id,
    environment_id,
    ssh_port,
)
from controller.runtime import engine
from controller.runtime.compose import Secret, Volume

_DATA_PATHS = HostDataPaths(root="/home/x/codespace")
_INSTANCE_PATHS = _DATA_PATHS.instance("devspace", "debug")


class ExecContainer(Protocol):
    def exec_run(
        self,
        command: list[str],
        *,
        user: str | None = None,
        demux: bool = False,
    ) -> tuple[int, tuple[bytes | None, bytes | None]]: ...


class FakeResponse:
    def __init__(self, *, payload: dict[str, object] | None = None, content: bytes = b"") -> None:
        self._payload = payload or {}
        self.content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, object]:
        return self._payload


def _frame(stream: int, content: bytes | None) -> bytes:
    if not content:
        return b""
    return bytes([stream, 0, 0, 0]) + len(content).to_bytes(4, "big") + content


class FakeAPIClient:
    def __init__(self, container: ExecContainer) -> None:
        self.container = container
        self.exit_code = 0
        self.output: tuple[bytes | None, bytes | None] = (None, None)
        self.start_timeouts: list[float | None] = []

    def post(
        self,
        path: str,
        *,
        data: str,
        timeout: float | None = None,
    ) -> FakeResponse:
        if path.endswith("/exec"):
            payload = json.loads(data)
            self.exit_code, self.output = self.container.exec_run(
                payload["Cmd"],
                user=payload["User"],
                demux=True,
            )
            return FakeResponse(payload={"Id": "exec-id"})
        self.start_timeouts.append(timeout)
        stdout, stderr = self.output
        return FakeResponse(content=_frame(1, stdout) + _frame(2, stderr))

    def get(self, path: str) -> FakeResponse:
        assert path == "/exec/exec-id/json"
        return FakeResponse(payload={"ExitCode": self.exit_code})


class FakePullClient:
    def __init__(self, pull: Callable[..., list[dict[str, str]]]) -> None:
        self.images = SimpleNamespace(pull=pull)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeContainer:
    def __init__(
        self,
        *,
        host: str = "home",
        workspace: str = "devspace",
        instance: str = "debug",
        repo: str = "curoky/devspace",
        provider: str = "github",
        image: str = "image:latest",
        platform: str = "native",
    ) -> None:
        self.name = environment_id(host, workspace, instance)
        self.id = "container-id"
        identity_port = ssh_port(self.name)
        self.labels = {
            LABEL_MANAGED: "true",
            LABEL_WORKSPACE: workspace,
            LABEL_INSTANCE: instance,
            LABEL_TYPE: "repo",
            LABEL_REPO: repo,
            LABEL_PROVIDER: provider,
            LABEL_IMAGE: image,
            LABEL_PLATFORM: platform,
            LABEL_SSH_PORT: str(identity_port),
        }
        self.attrs = {"State": "running"}
        self.status = "running"
        self.exec_calls: list[tuple[list[str], str | None]] = []
        self.log_calls: list[dict[str, object]] = []
        self.log_frames: list[bytes] = []
        self.client = FakeAPIClient(self)

    def reload(self) -> None:
        return None

    def logs(self, **kwargs: object) -> list[bytes]:
        self.log_calls.append(kwargs)
        return list(self.log_frames)

    def exec_run(
        self,
        command: list[str],
        *,
        user: str | None = None,
        demux: bool = False,
    ) -> tuple[int, tuple[bytes | None, bytes | None]]:
        self.exec_calls.append((command, user))
        return 1 if command[0] == "test" else 0, (None, None)


def test_read_environment_requires_complete_valid_labels(config: Config) -> None:
    container = FakeContainer()

    environment = inventory.read_environment(container, "home", config)  # type: ignore[arg-type]

    assert environment.id == "codespace-home-devspace-debug"
    assert environment.repo == "curoky/devspace"
    assert environment.platform == "native"
    assert environment.status == "running"

    del container.labels[LABEL_REPO]
    with pytest.raises(ValueError, match=r"missing required label codespace.repo"):
        inventory.read_environment(container, "home", config)  # type: ignore[arg-type]


def test_container_logs_requests_tail_and_joins_frames() -> None:
    container = FakeContainer()
    container.log_frames = [b"first line\n", b"second line\n"]

    logs = container_runtime.container_logs(container)  # type: ignore[arg-type]

    assert logs == "first line\nsecond line\n"
    assert container.log_calls == [
        {
            "stdout": True,
            "stderr": True,
            "stream": False,
            "timestamps": True,
            "tail": 2000,
        }
    ]


def test_container_logs_accepts_bytes_payload() -> None:
    container = FakeContainer()
    container.logs = lambda **kwargs: b"single blob"  # type: ignore[method-assign]

    assert container_runtime.container_logs(container) == "single blob"  # type: ignore[arg-type]


def test_pull_image_streams_with_isolated_long_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    clients: list[FakePullClient] = []
    client_options: list[dict[str, object]] = []

    def pull(image: str, **kwargs: object) -> list[dict[str, str]]:
        calls.append((image, kwargs))
        return [{"status": "Pulling"}, {"status": "Download complete"}]

    def client_factory(**kwargs: object) -> FakePullClient:
        client_options.append(kwargs)
        client = FakePullClient(pull)
        clients.append(client)
        return client

    monkeypatch.setattr(engine, "PodmanClient", client_factory)
    client = SimpleNamespace(
        api=SimpleNamespace(
            base_url=SimpleNamespace(geturl=lambda: "http+unix://%2Ftmp%2Fpodman.sock"),
            version="5.8.0",
        )
    )

    container_runtime.pull_image(client, "image:latest", None)  # type: ignore[arg-type]
    container_runtime.pull_image(client, "image:latest", "linux/arm64")  # type: ignore[arg-type]

    assert client_options == [
        {
            "base_url": "http+unix://%2Ftmp%2Fpodman.sock",
            "version": "5.8.0",
            "timeout": 15 * 60.0,
        },
        {
            "base_url": "http+unix://%2Ftmp%2Fpodman.sock",
            "version": "5.8.0",
            "timeout": 15 * 60.0,
        },
    ]
    assert calls == [
        ("image:latest", {"stream": True, "decode": True}),
        ("image:latest", {"stream": True, "decode": True, "platform": "linux/arm64"}),
    ]
    assert all(client.closed for client in clients)


def test_pull_image_raises_on_stream_error_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def pull(image: str, **kwargs: object) -> list[dict[str, str]]:
        return [{"status": "Pulling"}, {"error": "manifest unknown"}]

    pull_client = FakePullClient(pull)
    monkeypatch.setattr(engine, "PodmanClient", lambda **_kwargs: pull_client)
    client = SimpleNamespace(
        api=SimpleNamespace(
            base_url=SimpleNamespace(geturl=lambda: "http+unix://%2Ftmp%2Fpodman.sock"),
            version="5.8.0",
        )
    )

    with pytest.raises(PodmanError, match=r"failed to pull image:latest: manifest unknown"):
        container_runtime.pull_image(client, "image:latest", None)  # type: ignore[arg-type]
    assert pull_client.closed is True


def test_inventory_reports_unknown_workspace_as_error(config: Config) -> None:
    container = FakeContainer(workspace="unknown")
    client = SimpleNamespace(
        containers=SimpleNamespace(list=lambda **_kwargs: [container]),
    )

    current = inventory.list_inventory(client, "home", config)  # type: ignore[arg-type]

    assert current.environments == []
    assert current.errors == [
        "container codespace-home-unknown-debug references unknown workspace 'unknown'"
    ]


def test_read_environment_rejects_invalid_platform_label(config: Config) -> None:
    container = FakeContainer(platform="linux/riscv64")

    with pytest.raises(ValueError, match=r"invalid platform label 'linux/riscv64'"):
        inventory.read_environment(container, "home", config)  # type: ignore[arg-type]


def test_written_labels_cover_every_required_label(config: Config) -> None:
    repo_labels = config.environment_spec("devspace", "home", "debug")
    labels = repo_labels.labels()

    assert set(MANDATORY_LABELS) <= set(labels)

    blank_labels = config.environment_spec("scratch", "home", "debug").labels()
    assert set(MANDATORY_LABELS) <= set(blank_labels)
    assert LABEL_REPO not in blank_labels
    assert LABEL_PROVIDER not in blank_labels


def test_create_container_preserves_fixed_runtime_contract(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = FakeContainer()
    calls: list[tuple[str, dict[str, object]]] = []

    def run(image: str, **kwargs: object) -> FakeContainer:
        calls.append((image, kwargs))
        return container

    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    result = container_runtime.create_container(
        client,  # type: ignore[arg-type]
        config.environment_spec("devspace", "home", "debug"),
        _INSTANCE_PATHS,
        {"HTTP_PROXY": "http://host-proxy:3128"},
    )

    assert result is container
    image, kwargs = calls[0]
    assert image == config.workspaces.defaults.image
    assert kwargs["name"] == "codespace-home-devspace-debug"
    assert kwargs["network_mode"] == "host"
    assert kwargs["platform"] == "linux/arm64"
    assert kwargs["cap_add"] == ["NET_RAW", "SYS_ADMIN"]
    assert kwargs["security_opt"] == ["disable", "seccomp=unconfined"]
    assert kwargs["pids_limit"] == -1
    assert kwargs["ulimits"] == [{"Name": "memlock", "Soft": -1, "Hard": -1}]
    assert kwargs["environment"] == {
        "HTTP_PROXY": "http://host-proxy:3128",
        "SSHD_PORT": str(ssh_port("codespace-home-devspace-debug")),
    }
    assert kwargs["ports"] == {}
    assert kwargs["devices"] == []
    assert kwargs["labels"] == {
        **container.labels,
        LABEL_IMAGE: config.workspaces.defaults.image,
        LABEL_PLATFORM: "linux/arm64",
    }
    assert kwargs["mounts"] == [
        {
            "type": "bind",
            "source": "/home/x/codespace/workspaces/devspace/debug/workspace",
            "target": "/workspace",
        },
        {
            "type": "bind",
            "source": "/home/x/codespace/workspaces/devspace/debug/upload",
            "target": "/upload",
        },
        {
            "type": "bind",
            "source": "/home/x/codespace/workspaces/devspace/debug/cache",
            "target": "/cache",
        },
        {
            "type": "bind",
            "source": "/etc/krb5.conf",
            "target": "/etc/krb5.conf",
            "read_only": True,
        },
    ]


def test_create_container_rejects_host_environment_collision(
    config: Config,
) -> None:
    spec = config.environment_spec("devspace", "home", "debug")
    spec = replace(
        spec,
        container=spec.container.model_copy(
            update={"environment": {"HTTP_PROXY": "http://configured:3128"}}
        ),
    )

    with pytest.raises(ValueError, match=r"also set in container\.environment"):
        container_runtime.create_container(
            SimpleNamespace(),  # type: ignore[arg-type]
            spec,
            _INSTANCE_PATHS,
            {"HTTP_PROXY": "http://host-proxy:3128"},
        )


def test_create_container_injects_gpu_device(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = FakeContainer()
    calls: list[tuple[str, dict[str, object]]] = []

    def run(image: str, **kwargs: object) -> FakeContainer:
        calls.append((image, kwargs))
        return container

    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    spec = config.environment_spec("devspace", "home", "debug")
    spec = replace(
        spec,
        container=spec.container.model_copy(update={"devices": ["nvidia.com/gpu=all"]}),
    )
    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        spec,
        _INSTANCE_PATHS,
    )

    _, kwargs = calls[0]
    assert kwargs["devices"] == ["nvidia.com/gpu=all"]


def test_create_container_forwards_shm_size_only_when_set(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = FakeContainer()
    calls: list[tuple[str, dict[str, object]]] = []

    def run(image: str, **kwargs: object) -> FakeContainer:
        calls.append((image, kwargs))
        return container

    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    spec = config.environment_spec("devspace", "home", "debug")
    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        spec,
        _INSTANCE_PATHS,
    )
    _, kwargs = calls[0]
    assert "shm_size" not in kwargs

    calls.clear()
    spec = replace(
        spec,
        container=spec.container.model_copy(update={"shm_size": "100g"}),
    )
    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        spec,
        _INSTANCE_PATHS,
    )
    _, kwargs = calls[0]
    assert kwargs["shm_size"] == "100g"


class FakeSecretsManager:
    def __init__(self, existing: set[str]) -> None:
        self.existing = existing
        self.queried: list[str] = []

    def exists(self, key: str) -> bool:
        self.queried.append(key)
        return key in self.existing


def _run_capturing(calls: list[tuple[str, dict[str, object]]]) -> Callable[..., FakeContainer]:
    container = FakeContainer()

    def run(image: str, **kwargs: object) -> FakeContainer:
        calls.append((image, kwargs))
        return container

    return run


def test_create_container_forwards_registered_secrets(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    secrets = FakeSecretsManager({"supabase_service_key", "supabase_anon"})

    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(
        containers=SimpleNamespace(run=_run_capturing(calls)),
        secrets=secrets,
    )

    spec = config.environment_spec("devspace", "home", "debug")
    spec = replace(
        spec,
        container=spec.container.model_copy(
            update={
                "secrets": [
                    Secret(source="supabase_service_key"),
                    Secret(source="supabase_anon", mode="env", target="SUPABASE_ANON_KEY"),
                ]
            }
        ),
    )
    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        spec,
        _INSTANCE_PATHS,
    )

    _, kwargs = calls[0]
    assert kwargs["secrets"] == [
        {"source": "supabase_service_key", "uid": 5230, "gid": 5230, "mode": 0o400}
    ]
    assert kwargs["secret_env"] == {"SUPABASE_ANON_KEY": "supabase_anon"}
    assert set(secrets.queried) == {"supabase_service_key", "supabase_anon"}
    # Env secrets never leak into the plain environment mapping.
    assert "SUPABASE_ANON_KEY" not in kwargs["environment"]


def test_create_container_omits_secret_kwargs_when_unset(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(
        containers=SimpleNamespace(run=_run_capturing(calls)),
        secrets=FakeSecretsManager(set()),
    )

    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        config.environment_spec("devspace", "home", "debug"),
        _INSTANCE_PATHS,
    )

    _, kwargs = calls[0]
    assert "secrets" not in kwargs
    assert "secret_env" not in kwargs


def test_create_container_fails_fast_on_missing_secret(config: Config) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    client = SimpleNamespace(
        containers=SimpleNamespace(run=_run_capturing(calls)),
        secrets=FakeSecretsManager(set()),
    )

    spec = config.environment_spec("devspace", "home", "debug")
    spec = replace(
        spec,
        container=spec.container.model_copy(update={"secrets": [Secret(source="absent")]}),
    )

    with pytest.raises(RuntimeError, match=r"Podman secret 'absent' is not registered"):
        container_runtime.create_container(
            client,  # type: ignore[arg-type]
            spec,
            _INSTANCE_PATHS,
        )
    # The container must not be created when a referenced secret is missing.
    assert calls == []


def _encrypted_spec(config: Config) -> EnvironmentSpec:
    spec = config.environment_spec("devspace", "home", "debug")
    return replace(spec, workspace=spec.workspace.model_copy(update={"encrypt_workspace": True}))


def test_create_container_encrypts_workspace_when_enabled(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(
        containers=SimpleNamespace(run=_run_capturing(calls)),
        secrets=FakeSecretsManager({"workspace_crypt_key"}),
    )

    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        _encrypted_spec(config),
        _INSTANCE_PATHS,
    )

    _, kwargs = calls[0]
    mounts = kwargs["mounts"]
    assert isinstance(mounts, list)
    assert mounts[0]["target"] == "/workspace.enc"
    # The fixed crypt key is injected as env, like the sidecar's atuin_db_uri.
    assert kwargs["secret_env"] == {"WORKSPACE_CRYPT_KEY": "workspace_crypt_key"}


def test_create_container_fails_fast_on_missing_crypt_secret(config: Config) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    client = SimpleNamespace(
        containers=SimpleNamespace(run=_run_capturing(calls)),
        secrets=FakeSecretsManager(set()),
    )

    with pytest.raises(
        RuntimeError, match=r"Podman secret 'workspace_crypt_key' is not registered"
    ):
        container_runtime.create_container(
            client,  # type: ignore[arg-type]
            _encrypted_spec(config),
            _INSTANCE_PATHS,
        )
    assert calls == []


def test_create_container_uses_plaintext_workspace_when_disabled(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(
        containers=SimpleNamespace(run=_run_capturing(calls)),
        secrets=FakeSecretsManager(set()),
    )

    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        config.environment_spec("devspace", "home", "debug"),
        _INSTANCE_PATHS,
    )

    _, kwargs = calls[0]
    mounts = kwargs["mounts"]
    assert isinstance(mounts, list)
    assert mounts[0]["target"] == "/workspace"
    assert "secret_env" not in kwargs


def test_create_container_honors_custom_secret_mount_ownership(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(
        containers=SimpleNamespace(run=_run_capturing(calls)),
        secrets=FakeSecretsManager({"db_password"}),
    )

    spec = config.environment_spec("devspace", "home", "debug")
    spec = replace(
        spec,
        container=spec.container.model_copy(
            update={
                "secrets": [
                    Secret(
                        source="db_password",
                        target="/run/secrets/db",
                        uid=1000,
                        gid=1000,
                        file_mode=0o440,
                    )
                ]
            }
        ),
    )
    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        spec,
        _INSTANCE_PATHS,
    )

    _, kwargs = calls[0]
    assert kwargs["secrets"] == [
        {
            "source": "db_password",
            "uid": 1000,
            "gid": 1000,
            "mode": 0o440,
            "target": "/run/secrets/db",
        }
    ]


def test_create_container_bridge_publishes_ports_and_binds_sshd(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = FakeContainer()
    calls: list[tuple[str, dict[str, object]]] = []

    def run(image: str, **kwargs: object) -> FakeContainer:
        calls.append((image, kwargs))
        return container

    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    base = config.environment_spec("devspace", "home", "debug")
    spec = replace(
        base,
        host="local",
        platform=None,
        container=base.container.model_copy(update={"network_mode": "bridge"}),
        published_ports=((8080, 8080), (3000, 5000)),
    )
    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        spec,
        _INSTANCE_PATHS,
    )

    _, kwargs = calls[0]
    port = ssh_port("codespace-local-devspace-debug")
    assert kwargs["network_mode"] == "bridge"
    assert kwargs["environment"] == {"SSHD_PORT": str(port), "SSHD_BIND": "0.0.0.0"}  # noqa: S104
    assert kwargs["ports"] == {
        f"{port}/tcp": ("127.0.0.1", port),
        "8080/tcp": 8080,
        "5000/tcp": 3000,
    }


def test_create_container_blank_omits_repo_and_provider_labels(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = FakeContainer()
    calls: list[tuple[str, dict[str, object]]] = []

    def run(image: str, **kwargs: object) -> FakeContainer:
        calls.append((image, kwargs))
        return container

    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        config.environment_spec("scratch", "home", "debug"),
        _INSTANCE_PATHS,
    )

    _, kwargs = calls[0]
    labels = kwargs["labels"]
    assert isinstance(labels, dict)
    assert labels[LABEL_TYPE] == "blank"
    assert LABEL_REPO not in labels
    assert LABEL_PROVIDER not in labels


def test_bootstrap_invokes_workspace_helper_with_long_timeout() -> None:
    container = FakeContainer()

    workspace.bootstrap(
        container,  # type: ignore[arg-type]
        clone_url="git@gitlab.com:group/service-api.git",
        clone_path="/workspace/service-api",
        open_path="/workspace/service-api/src",
    )

    assert container.exec_calls == [
        (
            [
                "/opt/codespace/bin/codespace-git-checkout",
                "git@gitlab.com:group/service-api.git",
                "/workspace/service-api",
            ],
            "x",
        ),
        (
            [
                "/opt/codespace/bin/codespace-workspace-open-path",
                "/workspace/service-api/src",
            ],
            "x",
        ),
    ]
    assert container.client.start_timeouts == [15 * 60.0, 60.0]


def test_bootstrap_blank_only_passes_open_path() -> None:
    container = FakeContainer()

    workspace.bootstrap(
        container,  # type: ignore[arg-type]
        clone_url=None,
        clone_path="/workspace",
        open_path="/workspace/scratch",
    )

    assert container.exec_calls == [
        (
            [
                "/opt/codespace/bin/codespace-workspace-open-path",
                "/workspace/scratch",
            ],
            "x",
        )
    ]


def test_bootstrap_raises_when_helper_fails() -> None:
    container = FakeContainer()
    container.exec_run = lambda command, user=None, demux=False: (  # type: ignore[method-assign]
        container.exec_calls.append((command, user)) or (1, (None, b"boom"))
    )

    with pytest.raises(RuntimeError, match=r"codespace-git-checkout.* failed \(1\)"):
        workspace.bootstrap(
            container,  # type: ignore[arg-type]
            clone_url="git@github.com:curoky/devspace.git",
            clone_path="/workspace/devspace",
            open_path="/workspace/devspace",
        )


def test_bootstrap_raises_when_open_path_helper_fails() -> None:
    container = FakeContainer()
    container.exec_run = lambda command, user=None, demux=False: (  # type: ignore[method-assign]
        container.exec_calls.append((command, user)) or (1, (None, b"boom"))
    )

    with pytest.raises(RuntimeError, match=r"codespace-workspace-open-path.* failed \(1\)"):
        workspace.bootstrap(
            container,  # type: ignore[arg-type]
            clone_url=None,
            clone_path="/workspace",
            open_path="/workspace",
        )


def _environment_for_purge(platform: str) -> Environment:
    return Environment(
        id="codespace-home-devspace-debug",
        host="home",
        workspace="devspace",
        instance="debug",
        type="repo",
        repo="curoky/devspace",
        provider="github",
        image="image:latest",
        platform=platform,  # type: ignore[arg-type]
        ssh_port=22000,
        container_id="container-id",
    )


def test_purge_workspace_uses_environment_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    container = SimpleNamespace(stop=lambda *, timeout, ignore=False: None)
    calls: list[tuple[str, dict[str, object]]] = []

    class HelperContainer:
        def wait(self) -> int:
            return 0

        def logs(self, **_: object) -> list[bytes]:
            return []

        def remove(self, **_: object) -> None:
            return None

    def run(image: str, **kwargs: object) -> HelperContainer:
        calls.append((image, kwargs))
        return HelperContainer()

    monkeypatch.setattr(engine, "Container", HelperContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    container_runtime.purge_workspace(
        client,  # type: ignore[arg-type]
        container,  # type: ignore[arg-type]
        _environment_for_purge("linux/arm64"),
        _INSTANCE_PATHS,
    )

    assert calls[0][0] == "image:latest"
    assert calls[0][1]["platform"] == "linux/arm64"
    assert calls[0][1]["user"] == "0"
    assert calls[0][1]["security_opt"] == ["disable"]
    # The instance parent contains workspace, upload and cache, so one removal is enough.
    assert [call[1]["command"] for call in calls] == [
        ["-rf", "--", "/home/x/codespace/workspaces/devspace/debug"],
    ]


def test_purge_workspace_surfaces_rm_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    container = SimpleNamespace(stop=lambda *, timeout, ignore=False: None)
    removed: list[bool] = []

    class HelperContainer:
        def wait(self) -> int:
            return 1

        def logs(self, **_: object) -> list[bytes]:
            return [b"rm: cannot remove: Device or resource busy\n"]

        def remove(self, **_: object) -> None:
            removed.append(True)

    monkeypatch.setattr(engine, "Container", HelperContainer)
    client = SimpleNamespace(
        containers=SimpleNamespace(run=lambda image, **kwargs: HelperContainer()),
    )

    with pytest.raises(RuntimeError, match="Device or resource busy"):
        container_runtime.purge_workspace(
            client,  # type: ignore[arg-type]
            container,  # type: ignore[arg-type]
            _environment_for_purge("native"),
            _INSTANCE_PATHS,
        )

    assert removed == [True]


def test_remove_data_directory_rejects_target_outside_root() -> None:
    client = SimpleNamespace(
        containers=SimpleNamespace(run=lambda *_args, **_kwargs: pytest.fail("helper must not run"))
    )

    with pytest.raises(RuntimeError, match="outside root"):
        container_runtime.remove_data_directory(
            client,  # type: ignore[arg-type]
            "image:latest",
            "/home/x/codespace",
            "/home/x/other",
        )


class WorkspaceHelperFakeContainer:
    """Container stub scripting a single workspace helper reply.

    The in-image ``state`` command emits one JSON document. The stub returns
    ``(exit_code, stdout, stderr)`` for that single exec so the Python side only
    has to prove it invokes the helper and parses its JSON.
    """

    def __init__(self, reply: tuple[int, bytes, bytes]) -> None:
        self.reply = reply
        self.calls: list[tuple[list[str], str | None]] = []
        self.id = "git-container-id"
        self.name = "git-container"
        self.client = FakeAPIClient(self)

    def exec_run(
        self,
        command: list[str],
        *,
        user: str | None = None,
        demux: bool = False,
    ) -> tuple[int, tuple[bytes | None, bytes | None]]:
        self.calls.append((command, user))
        code, stdout, stderr = self.reply
        return code, (stdout or None, stderr or None)


def test_generate_deploy_key_invokes_helper_and_returns_public_key() -> None:
    container = WorkspaceHelperFakeContainer(
        (0, b'{"public_key":"ssh-ed25519 AAAAC3Nza test"}', b"")
    )

    public_key = workspace.generate_deploy_key(container)  # type: ignore[arg-type]

    assert public_key == "ssh-ed25519 AAAAC3Nza test"
    assert container.calls == [
        (
            ["/opt/codespace/bin/codespace-deploy-key"],
            "x",
        )
    ]


def test_generate_deploy_key_raises_on_helper_failure() -> None:
    container = WorkspaceHelperFakeContainer((1, b"", b"ssh-keygen failed"))

    with pytest.raises(RuntimeError, match=r"codespace-deploy-key failed \(1\)"):
        workspace.generate_deploy_key(container)  # type: ignore[arg-type]


def test_checkout_git_state_invokes_helper_and_parses_clean_json() -> None:
    container = WorkspaceHelperFakeContainer(
        (0, b'{"unpushed": false, "uncommitted": false, "detail": []}', b"")
    )

    state = workspace.checkout_git_state(container, "/workspace/devspace")  # type: ignore[arg-type]

    assert container.calls == [
        (
            [
                "/opt/codespace/bin/codespace-workspace-state",
                "/workspace/devspace",
            ],
            "x",
        )
    ]
    assert state.blocks_delete is False
    assert state.unpushed is False
    assert state.uncommitted is False
    assert state.detail == []


def test_checkout_git_state_parses_detected_changes() -> None:
    container = WorkspaceHelperFakeContainer(
        (
            0,
            b'{"unpushed": true, "uncommitted": true, '
            b'"detail": [" M models.py", "abc123 add feature"]}',
            b"",
        )
    )

    state = workspace.checkout_git_state(container, "/workspace/devspace")  # type: ignore[arg-type]

    assert state.blocks_delete is True
    assert state.unpushed is True
    assert state.uncommitted is True
    assert state.detail == [" M models.py", "abc123 add feature"]


def test_checkout_git_state_raises_on_helper_failure() -> None:
    container = WorkspaceHelperFakeContainer((1, b"", b"boom"))

    with pytest.raises(RuntimeError, match=r"codespace-workspace-state failed \(1\)"):
        workspace.checkout_git_state(container, "/workspace/devspace")  # type: ignore[arg-type]


# --- Deployment inventory ----------------------------------------------------


def _deployment_config() -> Config:
    return Config.model_validate(
        {
            "workspaces": {
                "defaults": {"image": "img", "container": {"network_mode": "host"}},
                "items": {
                    "devspace": {"host": [{"name": "server"}], "provider": "github", "repo": "o/r"}
                },
            },
            "hosts": {"server": {"deployments": ["sidecar"]}, "other": {}},
            "deployments": {
                "sidecar": {"image": "sidecar:latest", "container": {"network_mode": "host"}}
            },
        }
    )


class FakeDeploymentContainer:
    def __init__(
        self,
        *,
        deployment: str = "sidecar",
        image: str = "sidecar:latest",
        name: str | None = None,
        managed: bool = False,
    ) -> None:
        self.name = name or deployment_id(deployment)
        self.id = "deployment-id"
        self.labels: dict[str, str] = {
            LABEL_DEPLOYMENT: "true",
            LABEL_DEPLOYMENT_ID: deployment,
            LABEL_IMAGE: image,
        }
        if managed:
            self.labels[LABEL_MANAGED] = "true"
        self.attrs = {"State": "running"}
        self.status = "running"


def test_read_deployment_accepts_valid_labels() -> None:
    config = _deployment_config()
    container = FakeDeploymentContainer()

    deployment = inventory.read_deployment(container, "server", config)  # type: ignore[arg-type]

    assert deployment.id == "codespace-sidecar"
    assert deployment.deployment == "sidecar"
    assert deployment.image == "sidecar:latest"
    assert deployment.status == "running"


def test_read_deployment_rejects_managed_label() -> None:
    config = _deployment_config()
    container = FakeDeploymentContainer(managed=True)

    with pytest.raises(ValueError, match=r"must not carry codespace\.managed"):
        inventory.read_deployment(container, "server", config)  # type: ignore[arg-type]


def test_read_deployment_rejects_host_not_declaring_it() -> None:
    config = _deployment_config()
    container = FakeDeploymentContainer()

    with pytest.raises(ValueError, match="not configured for host"):
        inventory.read_deployment(container, "other", config)  # type: ignore[arg-type]


def test_list_deployments_collects_errors_for_unknown_deployment() -> None:
    config = _deployment_config()
    container = FakeDeploymentContainer(deployment="ghost", name="codespace-ghost")
    client = SimpleNamespace(
        containers=SimpleNamespace(list=lambda **_kwargs: [container]),
    )

    result = inventory.list_deployments(client, "server", config)  # type: ignore[arg-type]

    assert result.deployments == []
    assert result.errors == ["container codespace-ghost references unknown deployment 'ghost'"]


def test_deployment_and_environment_inventory_use_disjoint_filters() -> None:
    config = _deployment_config()
    deployment_container = FakeDeploymentContainer()
    environment_container = FakeContainer(workspace="devspace", host="server")

    def listing(**kwargs: object) -> list[object]:
        label = kwargs.get("filters", {}).get("label")  # type: ignore[union-attr]
        if label == f"{LABEL_DEPLOYMENT}=true":
            return [deployment_container]
        if label == f"{LABEL_MANAGED}=true":
            return [environment_container]
        return []

    client = SimpleNamespace(containers=SimpleNamespace(list=listing))

    deployments = inventory.list_deployments(client, "server", config)  # type: ignore[arg-type]
    assert [d.deployment for d in deployments.deployments] == ["sidecar"]
    assert deployments.errors == []


# --- Deployment container creation and lifecycle -----------------------------


def _llm_deployment_config() -> Config:
    """A deployment catalog exercising the LLM container shape (ipc/devices/data)."""
    return Config.model_validate(
        {
            "workspaces": {
                "defaults": {
                    "image": "img",
                    "container": {
                        "network_mode": "host",
                        "cap_add": ["NET_RAW"],
                        "ulimits": {"memlock": {"soft": -1, "hard": -1}},
                        "volumes": ["/etc/krb5.conf:/etc/krb5.conf:ro"],
                    },
                },
                "items": {
                    "devspace": {"host": [{"name": "gpu"}], "provider": "github", "repo": "o/r"}
                },
            },
            "hosts": {"gpu": {"deployments": ["llm-vllm"]}},
            "deployments": {
                "llm-vllm": {
                    "image": "llm-vllm:latest",
                    "published_ports": ["8003:8003"],
                    "container": {
                        "network_mode": "bridge",
                        "ipc": "host",
                        "cap_add": [],
                        "ulimits": {},
                        "devices": ["nvidia.com/gpu=all"],
                        "volumes": ["${DEPLOYMENT_DATA}:/root/.cache/huggingface"],
                        "environment": ["HF_HOME=/root/.cache/huggingface", "LLM_PORT=8003"],
                    },
                }
            },
        }
    )


def test_create_deployment_container_translates_llm_run_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _llm_deployment_config()
    spec = config.deployment_spec("llm-vllm", "gpu")
    calls: list[tuple[str, dict[str, object]]] = []

    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=_run_capturing(calls)))

    container_runtime.create_deployment_container(
        client,  # type: ignore[arg-type]
        spec,
        "/home/x/codespace/deployments/llm-vllm",
    )

    image, kwargs = calls[0]
    assert image == "llm-vllm:latest"
    assert kwargs["name"] == "codespace-llm-vllm"
    assert kwargs["network_mode"] == "bridge"
    assert kwargs["ipc_mode"] == "host"
    assert "shm_size" not in kwargs
    assert kwargs["devices"] == ["nvidia.com/gpu=all"]
    assert kwargs["ports"] == {"8003/tcp": 8003}
    assert kwargs["restart_policy"] == {"Name": "unless-stopped"}
    assert kwargs["environment"] == {
        "HF_HOME": "/root/.cache/huggingface",
        "LLM_PORT": "8003",
    }
    # The development-only global defaults are overridden away for a deployment.
    assert kwargs["cap_add"] == []
    assert kwargs["ulimits"] == []
    labels = kwargs["labels"]
    assert isinstance(labels, dict)
    assert labels[LABEL_DEPLOYMENT] == "true"
    assert labels[LABEL_DEPLOYMENT_ID] == "llm-vllm"
    assert LABEL_MANAGED not in labels
    # The ${DEPLOYMENT_DATA} source resolves to the managed per-id data root.
    assert kwargs["mounts"] == [
        {
            "type": "bind",
            "source": "/home/x/codespace/deployments/llm-vllm",
            "target": "/root/.cache/huggingface",
            "read_only": False,
        }
    ]


def test_create_deployment_container_rejects_unknown_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _llm_deployment_config()
    spec = config.deployment_spec("llm-vllm", "gpu")
    bad = replace(
        spec,
        container=spec.container.model_copy(
            update={
                "volumes": [Volume(source="${OTHER}", target="/data")],
            }
        ),
    )
    monkeypatch.setattr(engine, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=lambda *a, **k: FakeContainer()))

    with pytest.raises(ValueError, match="unknown placeholder"):
        container_runtime.create_deployment_container(
            client,  # type: ignore[arg-type]
            bad,
            "/home/x/codespace/deployments/llm-vllm",
        )


def test_reconcile_replaces_existing_container_and_prepares_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _llm_deployment_config()
    spec = config.deployment_spec("llm-vllm", "gpu")
    stages: list[str] = []
    removed: list[bool] = []
    prepared: list[list[str]] = []
    created: list[str] = []

    class Existing:
        def remove(self, *, force: bool) -> None:
            removed.append(force)

    client = SimpleNamespace(
        containers=SimpleNamespace(
            exists=lambda _name: True,
            get=lambda _name: Existing(),
        )
    )
    route = SimpleNamespace(host="gpu")

    monkeypatch.setattr(deployment_ops.containers, "pull_image", lambda *a, **k: None)
    monkeypatch.setattr(deployment_ops.ssh, "remote_data_paths", lambda _route: _DATA_PATHS)
    monkeypatch.setattr(
        deployment_ops.ssh,
        "prepare_directories",
        lambda _route, targets: prepared.append(targets),
    )
    monkeypatch.setattr(
        deployment_ops.containers,
        "create_deployment_container",
        lambda _client, _spec, _root: created.append(_spec.identity),
    )

    deployment_ops.reconcile(
        client,  # type: ignore[arg-type]
        route,  # type: ignore[arg-type]
        spec,
        stage=stages.append,
    )

    assert removed == [True]
    assert prepared == [["/home/x/codespace/deployments/llm-vllm"]]
    assert created == ["codespace-llm-vllm"]
    assert stages[0].startswith("pulling image")
    assert "creating container" in stages


def test_teardown_removes_container_and_optionally_purges_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _llm_deployment_config()
    spec = config.deployment_spec("llm-vllm", "gpu")
    removed: list[object] = []
    purged: list[tuple[str, str, str]] = []

    class Found:
        pass

    found = Found()
    client = SimpleNamespace()
    route = SimpleNamespace(host="gpu")

    monkeypatch.setattr(
        deployment_ops.inventory, "find_deployment_container", lambda *a, **k: found
    )
    monkeypatch.setattr(deployment_ops.containers, "remove_container", removed.append)
    monkeypatch.setattr(deployment_ops.ssh, "remote_data_paths", lambda _route: _DATA_PATHS)
    monkeypatch.setattr(
        deployment_ops.containers,
        "remove_data_directory",
        lambda _client, image, root, target: purged.append((image, root, target)),
    )

    was_removed = deployment_ops.teardown(
        client,  # type: ignore[arg-type]
        route,  # type: ignore[arg-type]
        spec,
        config,
        purge=True,
        stage=lambda _stage: None,
    )

    assert was_removed is True
    assert removed == [found]
    assert purged == [
        (
            "llm-vllm:latest",
            "/home/x/codespace/deployments",
            "/home/x/codespace/deployments/llm-vllm",
        )
    ]


def test_teardown_reports_missing_container_without_purge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _llm_deployment_config()
    spec = config.deployment_spec("llm-vllm", "gpu")

    monkeypatch.setattr(deployment_ops.inventory, "find_deployment_container", lambda *a, **k: None)
    monkeypatch.setattr(
        deployment_ops.containers,
        "remove_container",
        lambda *_a: pytest.fail("must not remove a missing container"),
    )

    was_removed = deployment_ops.teardown(
        SimpleNamespace(),  # type: ignore[arg-type]
        SimpleNamespace(host="gpu"),  # type: ignore[arg-type]
        spec,
        config,
        purge=False,
        stage=lambda _stage: None,
    )

    assert was_removed is False


def _summary_config() -> Config:
    """A catalog with two deployments spread across two hosts for projection tests."""
    return Config.model_validate(
        {
            "workspaces": {
                "defaults": {"image": "img", "container": {"network_mode": "host"}},
                "items": {
                    "devspace": {"host": [{"name": "gpu"}], "provider": "github", "repo": "o/r"}
                },
            },
            "hosts": {
                "gpu": {"deployments": ["llm-vllm", "sidecar"]},
                "edge": {"deployments": ["sidecar"]},
            },
            "deployments": {
                "llm-vllm": {
                    "image": "llm-vllm:latest",
                    "container": {"network_mode": "host"},
                },
                "sidecar": {"image": "sidecar:latest", "container": {"network_mode": "host"}},
            },
        }
    )


def _live_deployment(name: str, *, status: str) -> Deployment:
    return Deployment(
        id=deployment_id(name),
        deployment=name,
        host="gpu",
        image=f"{name}:latest",
        container_id="cid",
        status=status,
    )


def test_build_summaries_projects_state_per_declared_host() -> None:
    config = _summary_config()
    inventories = {
        "gpu": inventory.DeploymentInventory(
            deployments=[_live_deployment("sidecar", status="running")],
            errors=[],
        ),
        "edge": None,
    }
    operation = DeploymentOperation(
        id="op-1",
        host="gpu",
        deployment="llm-vllm",
        status="running",
        stage="pulling image",
    )
    operations = {("gpu", "llm-vllm"): operation}

    summaries = deployment_ops.build_summaries(config, inventories, operations)

    by_id = {s.id: s for s in summaries}
    # Every catalog entry appears, in catalog order.
    assert [s.id for s in summaries] == ["llm-vllm", "sidecar"]

    # llm-vllm only declared on gpu; container missing but an operation is attached.
    (vllm_gpu,) = by_id["llm-vllm"].hosts
    assert (vllm_gpu.host, vllm_gpu.state) == ("gpu", "missing")
    assert vllm_gpu.operation is operation

    # sidecar declared on both hosts: running on gpu, offline on edge.
    sidecar_hosts = {h.host: h for h in by_id["sidecar"].hosts}
    assert sidecar_hosts["gpu"].state == "running"
    assert sidecar_hosts["gpu"].container_id == "cid"
    assert sidecar_hosts["edge"].state == "missing"
    assert sidecar_hosts["edge"].error == "host offline"


def test_build_summaries_marks_present_but_stopped_container() -> None:
    config = _summary_config()
    inventories = {
        "gpu": inventory.DeploymentInventory(
            deployments=[_live_deployment("llm-vllm", status="exited")],
            errors=[],
        ),
        "edge": inventory.DeploymentInventory(deployments=[], errors=[]),
    }

    summaries = deployment_ops.build_summaries(config, inventories, {})

    vllm = next(s for s in summaries if s.id == "llm-vllm")
    (vllm_gpu,) = vllm.hosts
    assert vllm_gpu.state == "stopped"
    assert vllm_gpu.status == "exited"
