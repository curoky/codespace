"""Tests for canonical container models and Podman translation."""

from types import SimpleNamespace

import pytest
from podman.domain.containers import Container
from podman.errors import NotFound
from pydantic import ValidationError

from codespace.config import ContainerLayer
from codespace.runtime import container
from codespace.runtime.container import ContainerSpec, PortSpec, SecretSpec, VolumeSpec


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


@pytest.mark.parametrize("model", [ContainerLayer, ContainerSpec])
def test_container_models_accept_standard_compose_service_fields(
    model: type[ContainerLayer] | type[ContainerSpec],
) -> None:
    values = {
        "image": "registry.example.com/app:latest",
        "platform": "linux/amd64",
        "pull_policy": "always",
        "network_mode": "bridge",
        "restart": "unless-stopped",
    }

    spec = model.model_validate(values)

    assert spec.image == "registry.example.com/app:latest"
    assert spec.platform == "linux/amd64"
    assert spec.pull_policy == "always"
    assert spec.network_mode == "bridge"
    assert spec.restart == "unless-stopped"


@pytest.mark.parametrize(
    "field",
    ["cap_add", "security_opt", "ulimits", "volumes", "environment", "secrets", "devices", "ports"],
)
def test_runtime_spec_rejects_null_collections(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        ContainerSpec.model_validate({field: None})


@pytest.mark.parametrize("model", [ContainerLayer, ContainerSpec])
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
    model: type[ContainerLayer] | type[ContainerSpec],
    field: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(field)


@pytest.mark.parametrize("model", [ContainerLayer, ContainerSpec])
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
def test_container_rejects_removed_non_compose_syntax(
    model: type[ContainerLayer] | type[ContainerSpec],
    field: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(field)


@pytest.mark.parametrize("model", [ContainerLayer, ContainerSpec])
@pytest.mark.parametrize(
    "field",
    [
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
    ],
)
def test_container_rejects_ambiguous_volume_targets(
    model: type[ContainerLayer] | type[ContainerSpec],
    field: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(field)


@pytest.mark.parametrize("model", [ContainerLayer, ContainerSpec])
def test_container_preserves_literal_environment_and_duplicate_options(
    model: type[ContainerLayer] | type[ContainerSpec],
) -> None:
    spec = model.model_validate(
        {
            **({"image": "image"} if model is ContainerSpec else {}),
            "cap_add": ["NET_RAW", "NET_RAW"],
            "environment": {"PROMPT": "${USER}:$PATH"},
            "ulimits": {"NOFILE": {"soft": 1024, "hard": 1024}},
        }
    )

    assert spec.cap_add == ["NET_RAW", "NET_RAW"]
    assert spec.environment == {"PROMPT": "${USER}:$PATH"}
    assert spec.ulimits is not None
    assert "NOFILE" in spec.ulimits


@pytest.mark.parametrize("model", [ContainerLayer, ContainerSpec])
def test_volume_short_and_long_syntax_are_normalized(
    model: type[ContainerLayer] | type[ContainerSpec],
) -> None:
    spec = model.model_validate(
        {
            **({"image": "image"} if model is ContainerSpec else {}),
            "volumes": [
                "/host/a:/container/a:ro",
                {
                    "type": "bind",
                    "source": "/host/b",
                    "target": "/container/b",
                },
            ],
        }
    )

    assert spec.volumes is not None
    assert [(volume.source, volume.target, volume.read_only) for volume in spec.volumes] == [
        ("/host/a", "/container/a", True),
        ("/host/b", "/container/b", False),
    ]


@pytest.mark.parametrize("model", [ContainerLayer, ContainerSpec])
@pytest.mark.parametrize(
    ("volume", "message"),
    [
        ("/only-one", "source:target"),
        ("/host:/container:shared", "ro.*rw"),
    ],
)
def test_volume_short_syntax_rejects_invalid_entries(
    model: type[ContainerLayer] | type[ContainerSpec],
    volume: str,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        model.model_validate({"volumes": [volume]})


def test_secret_long_syntax_uses_compose_semantics() -> None:
    assert SecretSpec(source="token").mode == 0o444
    assert SecretSpec(source="token", mode=0o600).mode == 0o600
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


def test_volume_rejects_parent_traversal_in_target() -> None:
    with pytest.raises(ValidationError, match="must not contain"):
        VolumeSpec(type="bind", source="/host/data", target="/tmp/../workspace")


def test_volume_rejects_relative_source() -> None:
    with pytest.raises(ValidationError, match="absolute path"):
        VolumeSpec(type="bind", source="relative", target="/data")


def test_runtime_rejects_unresolved_resource_data_source() -> None:
    volume = VolumeSpec(type="bind", source="${RESOURCE_DATA}", target="/data")
    with pytest.raises(ValueError):
        container.create_container(
            SimpleNamespace(),  # type: ignore[arg-type]
            name="codespace-service-support",
            spec=ContainerSpec(image="image", volumes=[volume]),
            labels={},
        )


@pytest.mark.parametrize("source", ["${SERVICE_DATA}", "${OTHER_DATA}", "/${DATA}"])
def test_volume_rejects_unknown_source_interpolation(source: str) -> None:
    with pytest.raises(ValidationError, match=r"only .*RESOURCE_DATA"):
        VolumeSpec(type="bind", source=source, target="/data")


@pytest.mark.parametrize("model", [ContainerLayer, ContainerSpec])
def test_duplicate_port_target_is_rejected(
    model: type[ContainerLayer] | type[ContainerSpec],
) -> None:
    with pytest.raises(ValidationError, match="published more than once"):
        model.model_validate(
            {
                "ports": [
                    {"target": 80, "published": 8080, "host_ip": "127.0.0.1"},
                    {"target": 80, "published": 8081, "host_ip": "127.0.0.1"},
                ],
            }
        )


@pytest.mark.parametrize("host_ip", ["127.0.0.1", "::1"])
def test_create_container_translates_canonical_options(
    monkeypatch: pytest.MonkeyPatch, host_ip: str
) -> None:
    captured: dict[str, object] = {}
    fake = SimpleNamespace()
    client = SimpleNamespace(secrets=SimpleNamespace(exists=lambda _name: True))
    spec = ContainerSpec.model_validate(
        {
            "image": "image:latest",
            "platform": "linux/amd64",
            "pull_policy": "always",
            "network_mode": "bridge",
            "restart": "unless-stopped",
            "privileged": True,
            "ipc": "host",
            "pids_limit": 100,
            "shm_size": "8g",
            "ulimits": {"memlock": {"soft": -1, "hard": -1}},
            "ports": [
                {
                    "target": 8000,
                    "published": 3000,
                    "host_ip": host_ip,
                }
            ],
            "secrets": [{"source": "api_token", "mode": 0o400}],
            "devices": ["nvidia.com/gpu=all"],
            "environment": {"SERVE_HOST": "127.0.0.1"},
            "volumes": [
                "codespace-resource:/opt/resource:ro",
                "/host/cache:/cache",
            ],
        }
    )

    def run(_client: object, image: str, options: dict[str, object]) -> object:
        captured.update(image=image, options=options)
        return fake

    monkeypatch.setattr(container, "run_container", run)

    result = container.create_container(
        client,  # type: ignore[arg-type]
        name="codespace-service-api",
        spec=spec,
        labels={"codespace.kind": "service"},
    )

    assert result is fake
    assert captured["image"] == "image:latest"
    options = captured["options"]
    assert isinstance(options, dict)
    assert options["network_mode"] == "bridge"
    assert options["privileged"] is True
    assert options["platform"] == "linux/amd64"
    assert "networks" not in options
    assert options["ports"] == {"8000/tcp": (host_ip, 3000)}
    assert options["ipc_mode"] == "host"
    assert options["environment"] == {"SERVE_HOST": "127.0.0.1"}
    assert options["secrets"] == [{"source": "api_token", "uid": 0, "gid": 0, "mode": 0o400}]
    assert options["restart_policy"] == {"Name": "unless-stopped"}
    assert options["volumes"] == {"codespace-resource": {"bind": "/opt/resource", "mode": "ro"}}
    assert options["mounts"] == [
        {
            "type": "bind",
            "source": "/host/cache",
            "target": "/cache",
            "read_only": False,
        }
    ]


@pytest.mark.parametrize(
    "host_ip",
    [
        "",
        "localhost",
        "host.containers.internal",
        "0.0.0.0",  # noqa: S104 - rejected insecure input
        "10.88.0.1",
        "10.88.0.1/16",
        "999.1.1.1",
        1234,
    ],
)
def test_port_host_ip_requires_a_loopback_address(host_ip: object) -> None:
    with pytest.raises(ValidationError):
        PortSpec.model_validate({"target": 80, "published": 8080, "host_ip": host_ip})


def test_create_container_uses_configured_network(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        container, "run_container", lambda _client, _image, options: captured.update(options)
    )

    container.create_container(
        SimpleNamespace(),  # type: ignore[arg-type]
        name="container",
        spec=ContainerSpec(image="image", network_mode="host"),
        labels={},
    )

    assert captured["network_mode"] == "host"
    assert captured["ports"] == {}
    assert "networks" not in captured


def test_create_container_publishes_additional_tcp_ports_on_random_loopback_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        container, "run_container", lambda _client, _image, options: captured.update(options)
    )
    spec = ContainerSpec(
        image="image",
        ports=[PortSpec(target=8080, published=8110, host_ip="127.0.0.1")],
    )

    container.create_container(
        SimpleNamespace(),  # type: ignore[arg-type]
        name="container",
        spec=spec,
        labels={},
        random_tcp_ports=[8080, 8008],
    )

    assert captured["ports"] == {
        "8080/tcp": ("127.0.0.1", 8110),
        "8008/tcp": ("127.0.0.1", 0),
    }


def test_published_tcp_endpoint_reads_loopback_binding() -> None:
    running = Container(
        attrs={
            "NetworkSettings": {
                "Ports": {
                    "8008/tcp": [{"HostIp": "127.0.0.1", "HostPort": "42345"}],
                }
            }
        }
    )

    assert container.published_tcp_endpoint(running, 8008) == ("127.0.0.1", 42345)
    assert container.published_tcp_endpoint(running, 8080) is None


def test_missing_secret_fails_before_container_creation() -> None:
    client = SimpleNamespace(secrets=SimpleNamespace(exists=lambda _name: False))
    spec = ContainerSpec(
        image="image",
        secrets=[SecretSpec(source="api_token")],
    )

    with pytest.raises(RuntimeError, match="codespace secrets sync --apply"):
        container.create_container(
            client,  # type: ignore[arg-type]
            name="name",
            spec=spec,
            labels={},
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
        logs=lambda **kwargs: (calls.append(kwargs), iter([b"line", b"\n"]))[-1],
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


def test_wait_running_reports_exit_state_and_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    stopped = SimpleNamespace(
        name="space-codespace-default",
        status="exited",
        attrs={"State": {"Status": "exited", "ExitCode": 127, "OOMKilled": False, "Error": ""}},
        reload=lambda: None,
        logs=lambda **_kwargs: iter([b"env: 'execlineb': No such file or directory\n"]),
    )

    def fail(_container: object) -> None:
        raise container._ContainerNotRunning("not running")

    monkeypatch.setattr(container, "_reload_until_running", fail)

    with pytest.raises(
        RuntimeError,
        match=(
            r"container space-codespace-default did not reach running state "
            r"\(status=exited, exit_code=127\): env: 'execlineb': No such file or directory"
        ),
    ):
        container.wait_running(stopped)  # type: ignore[arg-type]


@pytest.mark.parametrize("exit_code", [0, 1, None])
def test_remove_data_requires_zero_exit_and_always_removes_helper(
    monkeypatch: pytest.MonkeyPatch, exit_code: int | None
) -> None:
    helper = Container(attrs={"Id": "helper", "Name": "helper"})
    events: list[str] = []
    monkeypatch.setattr(helper, "wait", lambda: exit_code)
    monkeypatch.setattr(helper, "logs", lambda **_kwargs: iter([b"rm failed"]))
    monkeypatch.setattr(helper, "remove", lambda **_kwargs: events.append("removed"))
    client = SimpleNamespace(containers=SimpleNamespace(run=lambda *_args, **_kwargs: helper))

    if exit_code == 0:
        container.remove_data_directory(client, "image", "/data", "/data/workspace")  # type: ignore[arg-type]
    else:
        with pytest.raises(RuntimeError, match="rm failed"):
            container.remove_data_directory(client, "image", "/data", "/data/workspace")  # type: ignore[arg-type]
    assert events == ["removed"]


@pytest.mark.parametrize("event", [{"error": "pull failed"}, "invalid event"])
def test_pull_does_not_ignore_invalid_events(
    monkeypatch: pytest.MonkeyPatch, event: object
) -> None:
    closed: list[bool] = []
    calls: list[tuple[str, dict[str, object]]] = []
    pull_client = SimpleNamespace(
        images=SimpleNamespace(
            pull=lambda image, **kwargs: (calls.append((image, kwargs)), iter([event]))[-1]
        ),
        close=lambda: closed.append(True),
    )
    client = SimpleNamespace(
        api=SimpleNamespace(base_url=SimpleNamespace(geturl=lambda: "unix:///socket"), version="1")
    )
    monkeypatch.setattr(container, "PodmanClient", lambda **_kwargs: pull_client)

    with pytest.raises((container.PodmanError, AttributeError)):
        container.pull_image(  # type: ignore[arg-type]
            client,
            "image",
            "linux/amd64",
            "never",
        )
    assert calls == [
        (
            "image",
            {
                "stream": True,
                "decode": True,
                "policy": "never",
                "platform": "linux/amd64",
            },
        )
    ]
    assert closed == [True]
