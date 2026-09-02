"""Tests for canonical container models and Podman translation."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from codespace.runtime import container
from codespace.runtime.container import ContainerSpec, SecretSpec, VolumeSpec


def test_container_layers_replace_named_mappings() -> None:
    base = ContainerSpec(
        network_mode="host",
        environment={"BASE": "1"},
        volumes={
            "base": VolumeSpec(source="/host/base", target="/container/base"),
        },
    )
    override = ContainerSpec(
        network_mode="bridge",
        environment={"PLACEMENT": "1"},
        volumes={
            "placement": VolumeSpec(
                source="/host/placement",
                target="/container/placement",
            )
        },
    )

    resolved = base.merged_with(override)

    assert resolved.network_mode == "bridge"
    assert resolved.environment == {"PLACEMENT": "1"}
    assert list(resolved.volumes or {}) == ["placement"]


@pytest.mark.parametrize(
    "field",
    [
        {"volumes": ["/host:/container"]},
        {"environment": ["NAME=value"]},
        {"secrets": ["token"]},
        {"ports": ["8080:80"]},
        {"ulimits": {"memlock": -1}},
    ],
)
def test_container_rejects_short_syntax(field: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ContainerSpec.model_validate(field)


def test_secret_modes_are_strict() -> None:
    assert SecretSpec(source="token").mode == "mount"
    assert SecretSpec(source="token", mode="env", target="TOKEN").target == "TOKEN"

    with pytest.raises(ValidationError, match="requires 'target'"):
        SecretSpec(source="token", mode="env")
    with pytest.raises(ValidationError, match="absolute"):
        SecretSpec(source="token", target="relative")


def test_configured_mounts_resolves_only_known_placeholder() -> None:
    volumes = {
        "data": VolumeSpec(source="${SERVICE_DATA}", target="/data"),
    }

    assert container.configured_mounts(
        volumes,
        placeholders={"${SERVICE_DATA}": "/host/data"},
    ) == [
        {
            "type": "bind",
            "source": "/host/data",
            "target": "/data",
            "read_only": False,
        }
    ]
    with pytest.raises(ValueError, match="unknown volume source placeholder"):
        container.configured_mounts(volumes)


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
            "ports": {"web": {"host": 3000, "container": 8000}},
            "secrets": {"api": {"source": "api_token", "mode": "env", "target": "API_TOKEN"}},
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
    assert options["secret_env"] == {"API_TOKEN": "api_token"}
    assert options["restart_policy"] == {"Name": "unless-stopped"}


def test_missing_secret_fails_before_container_creation() -> None:
    client = SimpleNamespace(secrets=SimpleNamespace(exists=lambda _name: False))
    spec = ContainerSpec(
        network_mode="host",
        secrets={"api": SecretSpec(source="api_token", mode="env", target="API_TOKEN")},
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
