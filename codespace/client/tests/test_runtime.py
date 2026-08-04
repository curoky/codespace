"""Tests for Podman inventory, fixed runtime parameters and container helpers."""

from __future__ import annotations

import io
import tarfile
from dataclasses import replace
from types import SimpleNamespace

import pytest
from podman.errors import NotFound, PodmanError

from codespace.client import container as container_runtime
from codespace.client import inventory, workspace
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
    LABEL_TYPE,
    MANDATORY_LABELS,
    Environment,
    environment_id,
    environment_labels,
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

    def reload(self) -> None:
        return None

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


def test_pull_image_streams_and_passes_platform_only_when_selected() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def pull(image: str, **kwargs: object) -> list[dict[str, str]]:
        calls.append((image, kwargs))
        return [{"status": "Pulling"}, {"status": "Download complete"}]

    client = SimpleNamespace(images=SimpleNamespace(pull=pull))

    container_runtime.pull_image(client, "image:latest", None)  # type: ignore[arg-type]
    container_runtime.pull_image(client, "image:latest", "linux/arm64")  # type: ignore[arg-type]

    assert calls == [
        ("image:latest", {"stream": True, "decode": True}),
        ("image:latest", {"stream": True, "decode": True, "platform": "linux/arm64"}),
    ]


def test_pull_image_raises_on_stream_error() -> None:
    def pull(image: str, **kwargs: object) -> list[dict[str, str]]:
        return [{"status": "Pulling"}, {"error": "manifest unknown"}]

    client = SimpleNamespace(images=SimpleNamespace(pull=pull))

    with pytest.raises(PodmanError, match=r"failed to pull image:latest: manifest unknown"):
        container_runtime.pull_image(client, "image:latest", None)  # type: ignore[arg-type]


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
    repo_labels = config.environment_spec("devspace", "debug")
    labels = environment_labels(repo_labels)

    assert set(MANDATORY_LABELS) <= set(labels)

    blank_labels = environment_labels(config.environment_spec("scratch", "debug"))
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
        config.environment_spec("devspace", "debug"),
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
    spec = config.environment_spec("devspace", "debug")
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

    spec = config.environment_spec("devspace", "debug")
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

    base = config.environment_spec("devspace", "debug")
    spec = replace(
        base,
        project=base.project.model_copy(update={"host": "local", "platform": None}),
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
        config.environment_spec("scratch", "debug"),
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


def test_clone_reuses_existing_checkout_and_uses_argument_list() -> None:
    container = FakeContainer()
    container.exec_run = lambda command, user=None, demux=False: (  # type: ignore[method-assign]
        container.exec_calls.append((command, user)) or (0, (None, None))
    )

    workspace.clone_repo(container, "curoky/devspace", "github")  # type: ignore[arg-type]

    assert container.exec_calls == [(["test", "-d", "/workspace/devspace/.git"], "x")]


def test_clone_missing_checkout_runs_git_without_shell() -> None:
    container = FakeContainer()

    workspace.clone_repo(container, "group/service-api", "gitlab")  # type: ignore[arg-type]

    assert container.exec_calls[-1] == (
        [
            "git",
            "clone",
            "--depth=1",
            "git@gitlab.com:group/service-api.git",
            "/workspace/service-api",
        ],
        "x",
    )


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


class GitFakeContainer:
    """Container stub scripting exec_run replies for git state probes.

    Replies are ``(exit_code, stdout, stderr)`` and ``exec_run`` honours
    ``demux=True`` by returning the streams separately, mirroring Podman's real
    wire format. This lets tests prove stderr never pollutes stdout parsing.
    """

    def __init__(self, replies: dict[str, tuple[int, bytes, bytes]]) -> None:
        self.replies = replies
        self.calls: list[tuple[list[str], str | None]] = []
        self.status = "running"
        self.started = False

    def reload(self) -> None:
        pass

    def start(self) -> None:
        self.started = True
        self.status = "running"

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


def test_repo_git_state_starts_stopped_container() -> None:
    container = GitFakeContainer({})
    container.status = "exited"

    workspace.repo_git_state(container, "curoky/devspace")  # type: ignore[arg-type]

    assert container.started is True


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
