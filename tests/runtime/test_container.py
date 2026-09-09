"""Tests for canonical container models and Podman translation."""

from types import SimpleNamespace

import pytest
from podman.domain.containers import Container
from podman.errors import NotFound
from pydantic import ValidationError

from codespace.runtime import container
from codespace.runtime.container import ContainerSpec, SecretSpec, VolumeSpec


@pytest.mark.parametrize("state", ["running", {"Status": "running"}])
def test_container_status_accepts_libpod_list_and_inspect(state: object) -> None:
    actual = Container(attrs={"Id": "container-id", "State": state})

    assert container.container_status(actual) == "running"


@pytest.mark.parametrize("state", [{}, {"Other": "running"}])
def test_container_status_does_not_invent_missing_state(state: dict[str, str]) -> None:
    with pytest.raises(KeyError):
        container.container_status(Container(attrs={"State": state}))


def test_find_container_checks_ownership_in_one_inspect() -> None:
    actual = Container(attrs={"Config": {"Labels": {"codespace.kind": "service"}}})
    calls: list[str] = []
    client = SimpleNamespace(
        containers=SimpleNamespace(get=lambda name: (calls.append(name), actual)[-1])
    )

    assert (
        container.find_container(
            client,  # type: ignore[arg-type]
            "codespace-service-support",
            labels={"codespace.kind": "service"},
        )
        is actual
    )
    assert calls == ["codespace-service-support"]
    with pytest.raises(RuntimeError, match="required labels"):
        container.find_container(
            client,  # type: ignore[arg-type]
            "codespace-service-support",
            labels={"codespace.kind": "workspace"},
        )


def test_find_container_returns_none_only_for_not_found() -> None:
    def get(_name: str) -> None:
        raise NotFound("missing")

    client = SimpleNamespace(containers=SimpleNamespace(get=get))

    assert container.find_container(client, "missing", labels={}) is None  # type: ignore[arg-type]


def test_container_layers_replace_lists_and_mappings() -> None:
    base = ContainerSpec(
        network_mode="host",
        environment={"BASE": "1"},
        volumes=[
            VolumeSpec(type="bind", source="/host/base", target="/container/base"),
        ],
    )
    override = ContainerSpec(
        network_mode="bridge",
        environment={"PLACEMENT": "1"},
        volumes=[
            VolumeSpec(
                type="bind",
                source="/host/placement",
                target="/container/placement",
            )
        ],
    )

    resolved = base.merged_with(override)

    assert resolved.network_mode == "bridge"
    assert resolved.environment == {"PLACEMENT": "1"}
    assert [volume.source for volume in resolved.volumes or []] == ["/host/placement"]


@pytest.mark.parametrize(
    "field",
    [
        {"environment": ["NAME=value"]},
        {"secrets": ["token"]},
        {"ports": ["8080:80"]},
        {"ulimits": {"memlock": -1}},
        {"pids_limit": "100"},
        {"shm_size": 1024},
    ],
)
def test_container_rejects_compose_forms_outside_supported_subset(
    field: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ContainerSpec.model_validate(field)


@pytest.mark.parametrize(
    "field",
    [
        {
            "secrets": {
                "api": {
                    "source": "api_token",
                    "mode": "env",
                    "target": "API_TOKEN",
                }
            }
        },
        {"ports": {"web": {"host": 3000, "container": 8000}}},
    ],
)
def test_container_rejects_removed_non_compose_syntax(field: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ContainerSpec.model_validate(field)


@pytest.mark.parametrize(
    "field",
    [
        {"cap_add": ["NET_RAW", "NET_RAW"]},
        {
            "volumes": [
                "/host/data:/data",
                {
                    "type": "bind",
                    "source": "/host/data",
                    "target": "/data",
                },
            ]
        },
        {"ulimits": {"NOFILE": {"soft": 1024, "hard": 1024}}},
        {"environment": {"VALUE": "${HOST_VALUE}"}},
    ],
)
def test_container_rejects_values_outside_compose_subset(
    field: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ContainerSpec.model_validate(field)


def test_volume_short_and_long_syntax_are_normalized() -> None:
    spec = ContainerSpec.model_validate(
        {
            "volumes": [
                "/host/a:/container/a:ro",
                {
                    "type": "bind",
                    "source": "/host/b",
                    "target": "/container/b",
                },
            ]
        }
    )

    assert spec.volumes is not None
    assert [(volume.source, volume.target, volume.read_only) for volume in spec.volumes] == [
        ("/host/a", "/container/a", True),
        ("/host/b", "/container/b", False),
    ]


@pytest.mark.parametrize(
    ("volume", "message"),
    [
        ("/only-one", "source:target"),
        ("/host:/container:shared", "ro.*rw"),
    ],
)
def test_volume_short_syntax_rejects_invalid_entries(volume: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ContainerSpec.model_validate({"volumes": [volume]})


def test_secret_long_syntax_uses_compose_semantics() -> None:
    assert SecretSpec(source="token").mode == 0o444
    assert SecretSpec(source="token", mode=0o666).mode == 0o444
    assert SecretSpec(source="token", target="/run/token").target == "/run/token"

    with pytest.raises(ValidationError, match="absolute"):
        SecretSpec(source="token", target="relative")
    with pytest.raises(ValidationError, match="valid Compose secret name"):
        SecretSpec(source="../token")


def test_volume_translates_to_podman_mount() -> None:
    volume = VolumeSpec(type="bind", source="/host/data", target="/data", read_only=True)

    assert volume.mount() == {
        "type": "bind",
        "source": "/host/data",
        "target": "/data",
        "read_only": True,
    }


@pytest.mark.parametrize("source", ["relative", "${SERVICE_DATA}", "${OTHER_DATA}", "/${DATA}"])
def test_runtime_rejects_unresolved_mount_sources(source: str) -> None:
    volume = VolumeSpec(type="bind", source=source, target="/data")

    with pytest.raises(ValueError):
        container.create_container(
            SimpleNamespace(),  # type: ignore[arg-type]
            "image",
            name="codespace-service-support",
            spec=ContainerSpec(network_mode="host", volumes=[volume]),
            environment={},
            labels={},
            mounts=[],
        )


def test_duplicate_port_target_is_rejected() -> None:
    with pytest.raises(ValidationError, match="published more than once"):
        ContainerSpec.model_validate(
            {
                "ports": [
                    {"target": 80, "published": 8080, "host_ip": "127.0.0.1"},
                    {"target": 80, "published": 8081, "host_ip": "127.0.0.1"},
                ]
            }
        )


def test_create_container_translates_canonical_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    fake = SimpleNamespace()
    client = SimpleNamespace(secrets=SimpleNamespace(exists=lambda _name: True))
    spec = ContainerSpec.model_validate(
        {
            "network_mode": "bridge",
            "ipc": "host",
            "pids_limit": 100,
            "shm_size": "8g",
            "ulimits": {"memlock": {"soft": -1, "hard": -1}},
            "ports": [
                {
                    "target": 8000,
                    "published": 3000,
                    "host_ip": "127.0.0.1",
                }
            ],
            "secrets": [{"source": "api_token", "mode": 0o400}],
            "devices": ["nvidia.com/gpu=all"],
        }
    )

    def run(_client: object, image: str, options: dict[str, object]) -> object:
        captured.update(image=image, options=options)
        return fake

    monkeypatch.setattr(container, "run_container", run)

    result = container.create_container(
        client,  # type: ignore[arg-type]
        "image:latest",
        name="codespace-service-api",
        spec=spec,
        environment={"SERVE_HOST": "127.0.0.1"},
        labels={"codespace.kind": "service"},
        mounts=[],
        restart_policy={"Name": "unless-stopped"},
    )

    assert result is fake
    options = captured["options"]
    assert isinstance(options, dict)
    assert options["ports"] == {"8000/tcp": ("127.0.0.1", 3000)}
    assert options["ipc_mode"] == "host"
    assert options["secrets"] == [{"source": "api_token", "uid": 0, "gid": 0, "mode": 0o400}]
    assert options["restart_policy"] == {"Name": "unless-stopped"}


def test_missing_secret_fails_before_container_creation() -> None:
    client = SimpleNamespace(secrets=SimpleNamespace(exists=lambda _name: False))
    spec = ContainerSpec(
        network_mode="host",
        secrets=[SecretSpec(source="api_token")],
    )

    with pytest.raises(RuntimeError, match="codespace secrets sync --apply"):
        container.create_container(
            client,  # type: ignore[arg-type]
            "image",
            name="name",
            spec=spec,
            environment={},
            labels={},
            mounts=[],
        )


@pytest.mark.parametrize(
    ("root", "target"),
    [
        ("/data/workspaces", "/data/workspaces"),
        ("/data/workspaces", "/data/other"),
        ("relative", "/data/workspaces/project/workspace"),
    ],
)
def test_remove_data_directory_rejects_unsafe_target(root: str, target: str) -> None:
    with pytest.raises(RuntimeError, match="refusing to remove"):
        container.remove_data_directory(
            SimpleNamespace(),  # type: ignore[arg-type]
            "image",
            root,
            target,
        )


def test_container_logs_requests_bounded_tail() -> None:
    calls: list[dict[str, object]] = []
    running = SimpleNamespace(
        logs=lambda **kwargs: (calls.append(kwargs), b"line\n")[-1],
    )

    assert container.container_logs(running) == "line\n"  # type: ignore[arg-type]
    assert calls == [
        {
            "stdout": True,
            "stderr": True,
            "stream": False,
            "timestamps": True,
            "tail": 2000,
        }
    ]


def test_container_log_snapshot_lists_and_reads_file_source() -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    responses = iter(
        [
            (0, (b"s6.workspace-agent.log\0s6.sshd.stdout.log\0", None)),
            (0, (b"agent line\n", None)),
        ]
    )
    running = SimpleNamespace(
        exec_run=lambda command, **kwargs: (
            calls.append((command, kwargs)),
            next(responses),
        )[-1],
    )

    snapshot = container.container_log_snapshot(  # type: ignore[arg-type]
        running,
        "s6.workspace-agent.log",
    )

    assert snapshot.source == "s6.workspace-agent.log"
    assert snapshot.sources == (
        "container",
        "s6.sshd.stdout.log",
        "s6.workspace-agent.log",
    )
    assert snapshot.logs == "agent line\n"
    assert calls == [
        (
            [
                "find",
                "/var/log",
                "-maxdepth",
                "1",
                "-type",
                "f",
                "-name",
                "s6.*.log",
                "-printf",
                "%f\\0",
            ],
            {"stdout": True, "stderr": True, "stream": False, "demux": True},
        ),
        (
            [
                "tail",
                "--bytes=1048576",
                "--",
                "/var/log/s6.workspace-agent.log",
            ],
            {"stdout": True, "stderr": True, "stream": False, "demux": True},
        ),
    ]


def test_container_log_snapshot_rejects_unknown_and_unsafe_sources() -> None:
    running = SimpleNamespace(exec_run=lambda *_args, **_kwargs: (0, (b"s6.sshd.log\0", None)))

    with pytest.raises(RuntimeError, match="not found"):
        container.container_log_snapshot(running, "s6.missing.log")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="invalid"):
        container.container_log_snapshot(running, "../sshd.log")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="invalid"):
        container.container_log_snapshot(running, "sshd.log")  # type: ignore[arg-type]


def test_container_log_snapshot_surfaces_exec_failure() -> None:
    running = SimpleNamespace(
        exec_run=lambda *_args, **_kwargs: (
            1,
            (None, b"find: /var/log: Permission denied\n"),
        )
    )

    with pytest.raises(RuntimeError, match="Permission denied"):
        container.container_log_snapshot(running)  # type: ignore[arg-type]
