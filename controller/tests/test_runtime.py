"""Tests for Podman inventory, fixed runtime parameters and container helpers."""

from __future__ import annotations

import io
import json
import tarfile
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from typing import Protocol

import pytest
from podman.errors import NotFound, PodmanError

from controller import container as container_runtime
from controller import inventory, workspace
from controller.compose import Secret
from controller.config import Config
from controller.models import (
    LABEL_IMAGE,
    LABEL_INSTANCE,
    LABEL_MANAGED,
    LABEL_PLATFORM,
    LABEL_PROJECT,
    LABEL_PROVIDER,
    LABEL_REPO,
    LABEL_SSH_PORT,
    LABEL_TYPE,
    MANDATORY_LABELS,
    Environment,
    environment_id,
    environment_labels,
    ssh_port,
)


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
        project: str = "devspace",
        instance: str = "debug",
        repo: str = "curoky/devspace",
        provider: str = "github",
        image: str = "image:latest",
        platform: str = "native",
    ) -> None:
        self.name = environment_id(host, project, instance)
        self.id = "container-id"
        identity_port = ssh_port(self.name)
        self.labels = {
            LABEL_MANAGED: "true",
            LABEL_PROJECT: project,
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
        self.archive: bytes | None = None
        self.archive_path: str | None = None
        self.files: dict[str, bytes] = {}
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

    def put_archive(self, path: str, archive: bytes) -> bool:
        self.archive_path = path
        self.archive = archive
        return True

    def get_archive(self, path: str) -> tuple[list[bytes], dict[str, object]]:
        if path not in self.files:
            raise NotFound(f"no such file: {path}")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            raw = self.files[path]
            info = tarfile.TarInfo(name=path.rsplit("/", 1)[-1])
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
        return [buffer.getvalue()], {}


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

    monkeypatch.setattr(container_runtime, "PodmanClient", client_factory)
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
    monkeypatch.setattr(container_runtime, "PodmanClient", lambda **_kwargs: pull_client)
    client = SimpleNamespace(
        api=SimpleNamespace(
            base_url=SimpleNamespace(geturl=lambda: "http+unix://%2Ftmp%2Fpodman.sock"),
            version="5.8.0",
        )
    )

    with pytest.raises(PodmanError, match=r"failed to pull image:latest: manifest unknown"):
        container_runtime.pull_image(client, "image:latest", None)  # type: ignore[arg-type]
    assert pull_client.closed is True


def test_inventory_reports_unknown_project_as_error(config: Config) -> None:
    container = FakeContainer(project="unknown")
    client = SimpleNamespace(
        containers=SimpleNamespace(list=lambda **_kwargs: [container]),
    )

    current = inventory.list_inventory(client, "home", config)  # type: ignore[arg-type]

    assert current.environments == []
    assert current.errors == [
        "container codespace-home-unknown-debug references unknown project 'unknown'"
    ]


def test_read_environment_rejects_invalid_platform_label(config: Config) -> None:
    container = FakeContainer(platform="linux/riscv64")

    with pytest.raises(ValueError, match=r"invalid platform label 'linux/riscv64'"):
        inventory.read_environment(container, "home", config)  # type: ignore[arg-type]


def test_written_labels_cover_every_required_label(config: Config) -> None:
    repo_labels = config.environment_spec("devspace", "home", "debug")
    labels = environment_labels(repo_labels)

    assert set(MANDATORY_LABELS) <= set(labels)

    blank_labels = environment_labels(config.environment_spec("scratch", "home", "debug"))
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

    monkeypatch.setattr(container_runtime, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    result = container_runtime.create_container(
        client,  # type: ignore[arg-type]
        config.environment_spec("devspace", "home", "debug"),
        "/home/x/codespace",
        {"HTTP_PROXY": "http://host-proxy:3128"},
    )

    assert result is container
    image, kwargs = calls[0]
    assert image == config.default_image
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
        LABEL_IMAGE: config.default_image,
        LABEL_PLATFORM: "linux/arm64",
    }
    assert kwargs["mounts"] == [
        {
            "type": "bind",
            "source": "/home/x/codespace/devspace/debug",
            "target": "/workspace",
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
            "/home/x/codespace",
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

    monkeypatch.setattr(container_runtime, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    spec = config.environment_spec("devspace", "home", "debug")
    spec = replace(
        spec,
        container=spec.container.model_copy(update={"devices": ["nvidia.com/gpu=all"]}),
    )
    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        spec,
        "/home/x/codespace",
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

    monkeypatch.setattr(container_runtime, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    spec = config.environment_spec("devspace", "home", "debug")
    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        spec,
        "/home/x/codespace",
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
        "/home/x/codespace",
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

    monkeypatch.setattr(container_runtime, "Container", FakeContainer)
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
        "/home/x/codespace",
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
    monkeypatch.setattr(container_runtime, "Container", FakeContainer)
    client = SimpleNamespace(
        containers=SimpleNamespace(run=_run_capturing(calls)),
        secrets=FakeSecretsManager(set()),
    )

    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        config.environment_spec("devspace", "home", "debug"),
        "/home/x/codespace",
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
            "/home/x/codespace",
        )
    # The container must not be created when a referenced secret is missing.
    assert calls == []


def test_create_container_honors_custom_secret_mount_ownership(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(container_runtime, "Container", FakeContainer)
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
        "/home/x/codespace",
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

    monkeypatch.setattr(container_runtime, "Container", FakeContainer)
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
        "/home/x/codespace",
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

    monkeypatch.setattr(container_runtime, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    container_runtime.create_container(
        client,  # type: ignore[arg-type]
        config.environment_spec("scratch", "home", "debug"),
        "/home/x/codespace",
    )

    _, kwargs = calls[0]
    labels = kwargs["labels"]
    assert isinstance(labels, dict)
    assert labels[LABEL_TYPE] == "blank"
    assert LABEL_REPO not in labels
    assert LABEL_PROVIDER not in labels


def test_inject_deploy_key_writes_only_private_key() -> None:
    container = FakeContainer()

    workspace.inject_deploy_key(
        container,  # type: ignore[arg-type]
        "PRIVATE",
    )

    assert container.archive_path == "/home/x/.ssh"
    assert container.archive is not None
    with tarfile.open(fileobj=io.BytesIO(container.archive), mode="r") as archive:
        assert archive.getnames() == ["repo_id_ed25519"]
        key = archive.getmember("repo_id_ed25519")
        assert key.mode == 0o600
        key_file = archive.extractfile(key)
        assert key_file is not None
        assert key_file.read() == b"PRIVATE"
    assert container.exec_calls == [(["chown", "x:x", "/home/x/.ssh/repo_id_ed25519"], "0")]


def test_clone_reuses_valid_existing_checkout() -> None:
    container = FakeContainer()
    container.exec_run = lambda command, user=None, demux=False: (  # type: ignore[method-assign]
        container.exec_calls.append((command, user)) or (0, (None, None))
    )

    workspace.clone_repo(container, "curoky/devspace", "github")  # type: ignore[arg-type]

    assert container.exec_calls == [
        (["test", "-d", "/workspace/devspace/.git"], "x"),
        (["git", "-C", "/workspace/devspace", "rev-parse", "--verify", "HEAD"], "x"),
    ]


def test_clone_missing_checkout_uses_temporary_directory_and_long_timeout() -> None:
    container = FakeContainer()

    workspace.clone_repo(container, "group/service-api", "gitlab")  # type: ignore[arg-type]

    assert (
        [
            "git",
            "clone",
            "--depth=1",
            "git@gitlab.com:group/service-api.git",
            "/workspace/service-api.codespace-clone",
        ],
        "x",
    ) in container.exec_calls
    assert container.exec_calls[-1] == (
        [
            "mv",
            "--",
            "/workspace/service-api.codespace-clone",
            "/workspace/service-api",
        ],
        "x",
    )
    clone_index = next(
        index
        for index, (command, _) in enumerate(container.exec_calls)
        if command[:2] == ["git", "clone"]
    )
    assert container.client.start_timeouts[clone_index] == 15 * 60.0
    assert all(
        timeout == 60.0
        for index, timeout in enumerate(container.client.start_timeouts)
        if index != clone_index
    )


def test_clone_replaces_incomplete_checkout() -> None:
    container = FakeContainer()

    def exec_run(
        command: list[str],
        *,
        user: str | None = None,
        demux: bool = False,
    ) -> tuple[int, tuple[None, None]]:
        container.exec_calls.append((command, user))
        if command == ["test", "-d", "/workspace/devspace/.git"]:
            return 0, (None, None)
        if command[:3] == ["git", "-C", "/workspace/devspace"]:
            return 128, (None, None)
        if command == [
            "test",
            "-f",
            "/workspace/devspace/.git/codespace-empty-repository",
        ]:
            return 1, (None, None)
        return 0, (None, None)

    container.exec_run = exec_run  # type: ignore[method-assign]

    workspace.clone_repo(container, "curoky/devspace", "github")  # type: ignore[arg-type]

    assert (["rm", "-rf", "--", "/workspace/devspace"], "x") in container.exec_calls
    assert (
        [
            "git",
            "clone",
            "--depth=1",
            "git@github.com:curoky/devspace.git",
            "/workspace/devspace.codespace-clone",
        ],
        "x",
    ) in container.exec_calls


def test_clone_reuses_successfully_cloned_empty_repository() -> None:
    container = FakeContainer()

    def exec_run(
        command: list[str],
        *,
        user: str | None = None,
        demux: bool = False,
    ) -> tuple[int, tuple[None, None]]:
        container.exec_calls.append((command, user))
        if command[0] == "git":
            return 128, (None, None)
        return 0, (None, None)

    container.exec_run = exec_run  # type: ignore[method-assign]

    workspace.clone_repo(container, "curoky/empty", "github")  # type: ignore[arg-type]

    assert container.exec_calls == [
        (["test", "-d", "/workspace/empty/.git"], "x"),
        (["git", "-C", "/workspace/empty", "rev-parse", "--verify", "HEAD"], "x"),
        (
            [
                "test",
                "-f",
                "/workspace/empty/.git/codespace-empty-repository",
            ],
            "x",
        ),
    ]


def test_prepare_open_path_makes_directory_as_container_user() -> None:
    container = FakeContainer()

    workspace.prepare_open_path(
        container,  # type: ignore[arg-type]
        "/workspace/relevance-pipeline",
    )

    assert container.exec_calls == [(["mkdir", "-p", "--", "/workspace/relevance-pipeline"], "x")]


def _environment_for_purge(platform: str) -> Environment:
    return Environment(
        id="codespace-home-devspace-debug",
        host="home",
        project="devspace",
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

    monkeypatch.setattr(container_runtime, "Container", HelperContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    container_runtime.purge_workspace(
        client,  # type: ignore[arg-type]
        container,  # type: ignore[arg-type]
        _environment_for_purge("linux/arm64"),
        "/home/x/codespace",
    )

    assert calls[0][0] == "image:latest"
    assert calls[0][1]["platform"] == "linux/arm64"
    assert calls[0][1]["user"] == "0"
    assert calls[0][1]["security_opt"] == ["disable"]


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

    monkeypatch.setattr(container_runtime, "Container", HelperContainer)
    client = SimpleNamespace(
        containers=SimpleNamespace(run=lambda image, **kwargs: HelperContainer()),
    )

    with pytest.raises(RuntimeError, match="Device or resource busy"):
        container_runtime.purge_workspace(
            client,  # type: ignore[arg-type]
            container,  # type: ignore[arg-type]
            _environment_for_purge("native"),
            "/home/x/codespace",
        )

    assert removed == [True]


def test_remove_workspace_rejects_target_outside_root() -> None:
    client = SimpleNamespace(
        containers=SimpleNamespace(run=lambda *_args, **_kwargs: pytest.fail("helper must not run"))
    )

    with pytest.raises(RuntimeError, match="outside root"):
        container_runtime.remove_workspace(
            client,  # type: ignore[arg-type]
            "image:latest",
            "/home/x/codespace",
            "/home/x/other",
        )


class GitFakeContainer:
    """Container stub scripting exec_run replies for git state probes.

    Replies are ``(exit_code, stdout, stderr)`` and ``exec_run`` honours
    ``demux=True`` by returning the streams separately, mirroring Podman's real
    wire format. This lets tests prove stderr never pollutes stdout parsing.
    """

    def __init__(self, replies: dict[str, tuple[int, bytes, bytes]]) -> None:
        self.replies = replies
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
        if command[0] == "test":
            code, stdout, stderr = self.replies.get("test", (0, b"", b""))
        else:
            # git commands: key on the subcommand after "-C <target>".
            code, stdout, stderr = self.replies.get(command[3], (0, b"", b""))
        return code, (stdout or None, stderr or None)


def test_repo_git_state_clean_when_nothing_pending() -> None:
    container = GitFakeContainer({})

    state = workspace.repo_git_state(container, "curoky/devspace")  # type: ignore[arg-type]

    assert state.blocks_delete is False
    assert state.unpushed is False
    assert state.uncommitted is False
    assert state.detail == []


def test_repo_git_state_ignores_stderr_noise() -> None:
    # Regression: without demux, git/conmon stderr diagnostics leaked into the
    # stdout parsed for porcelain/log output and falsely blocked deletion.
    container = GitFakeContainer(
        {
            "status": (0, b"", b"warning: could not open directory\n"),
            "log": (0, b"", b"[conmon:d]: exec with attach got start message\n"),
        }
    )

    state = workspace.repo_git_state(container, "curoky/devspace")  # type: ignore[arg-type]

    assert state.blocks_delete is False
    assert state.detail == []


def test_repo_git_state_detects_uncommitted() -> None:
    container = GitFakeContainer({"status": (0, b" M models.py\n", b"")})

    state = workspace.repo_git_state(container, "curoky/devspace")  # type: ignore[arg-type]

    assert state.uncommitted is True
    assert state.unpushed is False
    assert state.detail == [" M models.py"]


def test_repo_git_state_detects_unpushed() -> None:
    container = GitFakeContainer({"log": (0, b"abc123 add feature\n", b"")})

    state = workspace.repo_git_state(container, "curoky/devspace")  # type: ignore[arg-type]

    assert state.unpushed is True
    assert state.uncommitted is False
    assert state.detail == ["abc123 add feature"]


def test_repo_git_state_detects_both() -> None:
    container = GitFakeContainer(
        {
            "status": (0, b" M models.py\n", b""),
            "log": (0, b"abc123 add feature\n", b""),
        }
    )

    state = workspace.repo_git_state(container, "curoky/devspace")  # type: ignore[arg-type]

    assert state.blocks_delete is True
    assert state.detail == [" M models.py", "abc123 add feature"]


def test_repo_git_state_skips_absent_checkout() -> None:
    container = GitFakeContainer({"test": (1, b"", b"")})

    state = workspace.repo_git_state(container, "curoky/devspace")  # type: ignore[arg-type]

    assert state.blocks_delete is False
    # Only the presence probe should run when the checkout is missing.
    assert container.calls == [(["test", "-d", "/workspace/devspace/.git"], "x")]


def test_repo_git_state_raises_on_git_failure() -> None:
    container = GitFakeContainer({"status": (128, b"", b"fatal: not a git repository")})

    with pytest.raises(RuntimeError, match=r"exec git .* failed \(128\)"):
        workspace.repo_git_state(container, "curoky/devspace")  # type: ignore[arg-type]
