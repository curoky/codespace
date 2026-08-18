"""Tests for the out-of-band sidecar deployment tool."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console
from typer.testing import CliRunner

from controller.config import Config
from controller.tools import deploy_sidecar


@pytest.fixture
def config() -> Config:
    return Config.model_validate(
        {
            "default_image": "image",
            "container": {"network_mode": "host"},
            "hosts": {
                "home": {"podman_socket": "/tmp/podmanxd.sock"},
                "office": {},
                "local": {"type": "podman-machine", "machine": "podman-machine-default"},
            },
            "secrets": {"atuin_db_uri": "postgres://db"},
            "projects": {
                "devspace": {
                    "repo": "github:owner/repo",
                    "host": [{"name": "home"}, {"name": "office"}, {"name": "local"}],
                }
            },
        }
    )


class FakeSecrets:
    def __init__(self, existing: set[str]) -> None:
        self.existing = set(existing)

    def exists(self, key: str) -> bool:
        return key in self.existing


class FakeContainer:
    def __init__(self, name: str) -> None:
        self.name = name
        self.status = "running"
        self.removed = False

    def remove(self, force: bool = False) -> None:
        self.removed = True

    def reload(self) -> None:
        pass


class FakeContainers:
    def __init__(self, existing: dict[str, FakeContainer]) -> None:
        self.existing = dict(existing)
        self.runs: list[dict[str, object]] = []

    def exists(self, key: str) -> bool:
        return key in self.existing

    def get(self, key: str) -> FakeContainer:
        return self.existing[key]

    def run(self, image: str, **kwargs: object) -> FakeContainer:
        self.runs.append({"image": image, **kwargs})
        return FakeContainer(str(kwargs["name"]))


class FakeClient:
    def __init__(self, secrets: FakeSecrets, containers: FakeContainers) -> None:
        self.secrets = secrets
        self.containers = containers

    @property
    def api(self) -> object:  # pragma: no cover - pull_image is patched out
        raise AssertionError("api access must be patched in tests")


class FakeTransport:
    def __init__(self, clients: dict[str, FakeClient]) -> None:
        self.clients = clients
        self.closed = False

    def client(self, host: str) -> FakeClient:
        return self.clients[host]

    def close(self) -> None:
        self.closed = True


def _run(
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    transport: FakeTransport,
    arguments: list[str],
) -> str:
    output = StringIO()
    monkeypatch.setattr(deploy_sidecar, "console", Console(file=output, width=120))
    monkeypatch.setattr(deploy_sidecar, "load_config", lambda _path: config)
    monkeypatch.setattr(deploy_sidecar, "PodmanTransport", lambda _hosts: transport)
    monkeypatch.setattr(deploy_sidecar, "pull_image", lambda *args, **kwargs: None)
    monkeypatch.setattr(deploy_sidecar, "Container", FakeContainer)
    result = CliRunner().invoke(deploy_sidecar.app, arguments)
    assert result.exit_code == 0
    return output.getvalue()


def test_dry_run_reports_plan_for_ssh_hosts_only(
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
) -> None:
    clients = {
        "home": FakeClient(FakeSecrets({"atuin_db_uri"}), FakeContainers({})),
        "office": FakeClient(
            FakeSecrets({"atuin_db_uri"}),
            FakeContainers({"codespace-sidecar": FakeContainer("codespace-sidecar")}),
        ),
    }
    transport = FakeTransport(clients)

    rendered = _run(monkeypatch, config, transport, [])

    # The podman-machine 'local' host is skipped: only the two SSH hosts appear.
    assert "Dry run: 2 sidecar(s)" in rendered
    assert "create" in rendered
    assert "replace" in rendered
    assert clients["home"].containers.runs == []
    assert transport.closed is True


def test_missing_secret_is_reported_and_skipped(
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
) -> None:
    clients = {
        "home": FakeClient(FakeSecrets(set()), FakeContainers({})),
        "office": FakeClient(FakeSecrets({"atuin_db_uri"}), FakeContainers({})),
    }
    transport = FakeTransport(clients)

    rendered = _run(monkeypatch, config, transport, [])

    assert "Dry run: 1 sidecar(s)" in rendered
    assert "missing podman secret 'atuin_db_uri'" in rendered


def test_no_dry_run_deploys_sidecar_on_all_ssh_hosts(
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
) -> None:
    existing = FakeContainer("codespace-sidecar")
    home = FakeClient(FakeSecrets({"atuin_db_uri"}), FakeContainers({}))
    office = FakeClient(
        FakeSecrets({"atuin_db_uri"}),
        FakeContainers({"codespace-sidecar": existing}),
    )
    transport = FakeTransport({"home": home, "office": office})

    rendered = _run(monkeypatch, config, transport, ["--no-dry-run"])

    assert "Deployed 2 sidecar(s)." in rendered
    # office had an existing sidecar: it is replaced before the new run.
    assert existing.removed is True
    assert len(home.containers.runs) == 1
    assert len(office.containers.runs) == 1

    run = home.containers.runs[0]
    assert run["image"] == "ghcr.io/curoky/devspace:codespace-sidecar"
    assert run["name"] == "codespace-sidecar"
    assert run["network_mode"] == "host"
    assert run["restart_policy"] == {"Name": "unless-stopped"}
    assert run["secret_env"] == {"ATUIN_DB_URI": "atuin_db_uri"}
    # The host socket path is bind-mounted at the fixed container path.
    assert run["mounts"] == [
        {
            "type": "bind",
            "source": "/tmp/podmanxd.sock",
            "target": "/run/podman/podman.sock",
        }
    ]


def test_no_ssh_hosts_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config.model_validate(
        {
            "default_image": "image",
            "container": {"network_mode": "bridge"},
            "hosts": {
                "local": {"type": "podman-machine", "machine": "podman-machine-default"},
            },
            "projects": {"devspace": {"repo": "github:owner/repo", "host": [{"name": "local"}]}},
        }
    )
    output = StringIO()
    monkeypatch.setattr(deploy_sidecar, "console", Console(file=output, width=120))
    monkeypatch.setattr(deploy_sidecar, "load_config", lambda _path: config)

    def _fail(_hosts: object) -> None:
        raise AssertionError("transport must not be created when no SSH hosts exist")

    monkeypatch.setattr(deploy_sidecar, "PodmanTransport", _fail)

    result = CliRunner().invoke(deploy_sidecar.app, [])

    assert result.exit_code == 0
    assert "runs only on non-local hosts" in output.getvalue()
