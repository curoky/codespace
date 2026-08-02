"""Tests for Podman inventory, fixed runtime parameters and container helpers."""

from __future__ import annotations

import io
import tarfile
from types import SimpleNamespace

import pytest
from podman.errors import NotFound

from codespace.client import runtime
from codespace.client.config import Config
from codespace.client.models import (
    LABEL_IMAGE,
    LABEL_INSTANCE,
    LABEL_MANAGED,
    LABEL_PLATFORM,
    LABEL_PROJECT,
    LABEL_PROVIDER,
    LABEL_REPO,
    LABEL_SSH_PORT,
    environment_id,
    ssh_port,
)


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
        self.files: dict[str, bytes] = {}

    def reload(self) -> None:
        return None

    def exec_run(
        self,
        command: list[str],
        *,
        user: str | None = None,
    ) -> tuple[int, bytes]:
        self.exec_calls.append((command, user))
        return 1 if command[0] == "test" else 0, b""

    def put_archive(self, _path: str, archive: bytes) -> bool:
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

    environment = runtime.read_environment(container, "home", config)  # type: ignore[arg-type]

    assert environment.id == "codespace-home-devspace-debug"
    assert environment.repo == "curoky/devspace"
    assert environment.platform == "native"
    assert environment.status == "running"

    del container.labels[LABEL_REPO]
    with pytest.raises(ValueError, match=r"missing required label codespace.repo"):
        runtime.read_environment(container, "home", config)  # type: ignore[arg-type]


def test_pull_image_passes_configured_platform_only_when_selected() -> None:
    calls: list[tuple[str, dict[str, str]]] = []
    client = SimpleNamespace(
        images=SimpleNamespace(pull=lambda image, **kwargs: calls.append((image, kwargs))),
    )

    runtime.pull_image(client, "image:latest", None)  # type: ignore[arg-type]
    runtime.pull_image(client, "image:latest", "linux/arm64")  # type: ignore[arg-type]

    assert calls == [
        ("image:latest", {}),
        ("image:latest", {"platform": "linux/arm64"}),
    ]


def test_inventory_reports_unknown_project_as_error(config: Config) -> None:
    container = FakeContainer(project="unknown")
    client = SimpleNamespace(
        containers=SimpleNamespace(list=lambda **_kwargs: [container]),
    )

    inventory = runtime.list_inventory(client, "home", config)  # type: ignore[arg-type]

    assert inventory.environments == []
    assert inventory.errors == [
        "container codespace-home-unknown-debug references unknown project 'unknown'"
    ]


def test_read_environment_rejects_invalid_platform_label(config: Config) -> None:
    container = FakeContainer(platform="linux/riscv64")

    with pytest.raises(ValueError, match=r"invalid platform label 'linux/riscv64'"):
        runtime.read_environment(container, "home", config)  # type: ignore[arg-type]


def test_create_container_preserves_fixed_runtime_contract(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = FakeContainer()
    calls: list[tuple[str, dict[str, object]]] = []

    def run(image: str, **kwargs: object) -> FakeContainer:
        calls.append((image, kwargs))
        return container

    monkeypatch.setattr(runtime, "Container", FakeContainer)
    client = SimpleNamespace(containers=SimpleNamespace(run=run))

    result = runtime.create_container(
        client,  # type: ignore[arg-type]
        host="home",
        project="devspace",
        instance="debug",
        repo="curoky/devspace",
        provider="github",
        image=config.project_image("devspace"),
        platform="linux/arm64",
        workspace_root="/home/x/codespace2",
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
    assert kwargs["environment"] == {"SSHD_PORT": str(ssh_port("codespace-home-devspace-debug"))}
    assert kwargs["labels"] == {
        **container.labels,
        LABEL_IMAGE: config.default_image,
        LABEL_PLATFORM: "linux/arm64",
    }
    assert kwargs["mounts"] == [
        {
            "type": "bind",
            "source": "/home/x/codespace2/devspace/debug",
            "target": "/workspace",
        },
        {
            "type": "bind",
            "source": "/etc/krb5.conf",
            "target": "/etc/krb5.conf",
            "read_only": True,
        },
    ]


def _archived_config(container: FakeContainer) -> str:
    assert container.archive is not None
    with tarfile.open(fileobj=io.BytesIO(container.archive), mode="r") as archive:
        assert set(archive.getnames()) == {
            "authorized_keys",
            "repo_id_ed25519",
            "config",
        }
        config_file = archive.extractfile("config")
        assert config_file is not None
        return config_file.read().decode()


def test_inject_credentials_writes_managed_block_when_no_config() -> None:
    container = FakeContainer()

    runtime.inject_credentials(
        container,  # type: ignore[arg-type]
        login_public_key="ssh-ed25519 LOGIN",
        deploy_private_key="PRIVATE",
        provider="github",
    )

    config = _archived_config(container)
    assert "Host github.com" in config
    assert config.count("# >>> codespace managed >>>") == 1
    assert all(command[0] != "sh" for command, _user in container.exec_calls)


def test_inject_credentials_appends_and_preserves_user_entries() -> None:
    container = FakeContainer()
    container.files["/home/x/.ssh/config"] = (
        b"Host my-server\n    HostName 10.0.0.1\n    User dev\n"
    )

    runtime.inject_credentials(
        container,  # type: ignore[arg-type]
        login_public_key="ssh-ed25519 LOGIN",
        deploy_private_key="PRIVATE",
        provider="github",
    )

    config = _archived_config(container)
    assert "Host my-server" in config
    assert "Host github.com" in config
    assert config.count("# >>> codespace managed >>>") == 1
    assert (
        ["rm", "-f", "/home/x/.ssh/config"],
        "0",
    ) in container.exec_calls


def test_inject_credentials_replaces_stale_managed_block() -> None:
    container = FakeContainer()
    container.files["/home/x/.ssh/config"] = (
        b"Host my-server\n    HostName 10.0.0.1\n\n"
        b"# >>> codespace managed >>>\n"
        b"Host gitlab.com\n    HostName gitlab.com\n"
        b"# <<< codespace managed <<<\n"
    )

    runtime.inject_credentials(
        container,  # type: ignore[arg-type]
        login_public_key="ssh-ed25519 LOGIN",
        deploy_private_key="PRIVATE",
        provider="github",
    )

    config = _archived_config(container)
    assert "Host my-server" in config
    assert "Host github.com" in config
    assert "gitlab.com" not in config
    assert config.count("# >>> codespace managed >>>") == 1


def test_clone_reuses_existing_checkout_and_uses_argument_list() -> None:
    container = FakeContainer()
    container.exec_run = lambda command, user=None: (  # type: ignore[method-assign]
        container.exec_calls.append((command, user)) or (0, b"")
    )

    runtime.clone_repo(container, "curoky/devspace", "github")  # type: ignore[arg-type]

    assert container.exec_calls == [(["test", "-d", "/workspace/devspace/.git"], "x")]


def test_clone_missing_checkout_runs_git_without_shell() -> None:
    container = FakeContainer()

    runtime.clone_repo(container, "group/service-api", "gitlab")  # type: ignore[arg-type]

    assert container.exec_calls[-1] == (
        [
            "git",
            "clone",
            "git@gitlab.com:group/service-api.git",
            "/workspace/service-api",
        ],
        "x",
    )


def test_purge_workspace_uses_environment_platform() -> None:
    container = SimpleNamespace(stop=lambda *, timeout: None)
    calls: list[tuple[str, dict[str, object]]] = []
    client = SimpleNamespace(
        containers=SimpleNamespace(
            run=lambda image, **kwargs: calls.append((image, kwargs)),
        )
    )

    runtime.purge_workspace(
        client,  # type: ignore[arg-type]
        container,  # type: ignore[arg-type]
        "image:latest",
        "linux/arm64",
        "/home/x/codespace2",
        "devspace",
        "debug",
    )

    assert calls[0][0] == "image:latest"
    assert calls[0][1]["platform"] == "linux/arm64"
