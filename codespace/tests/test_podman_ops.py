"""Tests for the pure helpers in podman_ops (no podman service needed)."""

import io
import tarfile
from pathlib import Path

import pytest

from codespace import shared
from codespace.agent import podman_ops


class _FakeContainer:
    """Minimal stand-in exposing the attributes the helpers read."""

    def __init__(
        self, labels: dict[str, str], ports: dict | None = None, status: str = "running"
    ) -> None:
        self.labels = labels
        self.ports = {"22/tcp": [{"HostPort": "49207"}]} if ports is None else ports
        self.status = status
        self.attrs = {"State": {"Status": status}}
        self.id = "deadbeef"
        cs_id = labels.get(shared.LABEL_ID, "")
        self.name = shared.container_name(cs_id) if cs_id else ""

    def reload(self) -> None:  # to_codespace -> _host_port calls reload()
        pass


def test_multi_member_tar_contains_members_with_modes() -> None:
    archive = podman_ops._multi_member_tar(
        [
            ("repo_id_ed25519", "PRIVATE", 0o600),
            ("config", "cfg", 0o600),
        ]
    )
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r") as tar:
        names = tar.getnames()
        assert names == ["repo_id_ed25519", "config"]
        member = tar.getmember("repo_id_ed25519")
        assert member.mode == 0o600
        extracted = tar.extractfile("repo_id_ed25519")
        assert extracted is not None
        assert extracted.read() == b"PRIVATE"


def test_read_label_returns_default_when_absent() -> None:
    container = _FakeContainer(labels={})
    assert podman_ops.read_label(container, shared.LABEL_REPO, "fallback") == "fallback"


def test_read_label_reads_value() -> None:
    container = _FakeContainer(labels={shared.LABEL_REPO: "owner/name"})
    assert podman_ops.read_label(container, shared.LABEL_REPO) == "owner/name"


def test_to_codespace_maps_labels_and_port() -> None:
    container = _FakeContainer(
        labels={
            shared.LABEL_ID: "abc123",
            shared.LABEL_REPO: "owner/name",
            shared.LABEL_WORKSPACE: "default",
            shared.LABEL_USER: "dev",
        }
    )
    cs = podman_ops.to_codespace(container)
    assert cs.id == "abc123"
    assert cs.repo == "owner/name"
    assert cs.port == 49207
    assert cs.deploy_keys == []
    assert cs.workspace_dir == shared.workspace_dir_name("owner/name", "default")
    assert cs.status == "running"


def test_to_codespace_reads_status_when_podman_state_is_string() -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "abc123"})
    container.attrs = {"State": "exited"}

    cs = podman_ops.to_codespace(container)

    assert cs.status == "exited"


def test_to_codespace_tolerates_missing_port() -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "x"}, ports={})
    cs = podman_ops.to_codespace(container)
    assert cs.port == 0


# --- Orchestration tests with a fake podman client ---------------------------


class _ExecContainer(_FakeContainer):
    """Container stub recording exec/put_archive calls for injection tests."""

    def __init__(self, labels: dict[str, str], home: str | bytes = "/home/dev") -> None:
        super().__init__(labels)
        self._home = home
        self.execs: list[tuple[list[str], str | None]] = []
        self.archives: list[tuple[str, bytes]] = []

    def exec_run(self, cmd: list[str], *, user: str | None = None) -> tuple[int, bytes]:
        self.execs.append((cmd, user))
        if cmd[:2] == ["sh", "-c"]:  # HOME resolution
            home = self._home if isinstance(self._home, bytes) else self._home.encode()
            return 0, home
        return 0, b""

    def put_archive(self, path: str, data: bytes) -> bool:
        self.archives.append((path, data))
        return True


class _FakeContainers:
    def __init__(self, container: _FakeContainer | None = None) -> None:
        self._container = container
        self.runs: list[dict] = []
        self.removed: list[str] = []

    def run(self, image: str, **kwargs: object) -> "_FakeContainer | bytes | None":
        self.runs.append({"image": image, **kwargs})
        if kwargs.get("detach"):
            return self._container
        return b""

    def get(self, name: str) -> _FakeContainer:
        if self._container is None:
            from podman.errors import NotFound

            raise NotFound(name)
        return self._container

    def list(self, all: bool = False) -> list[_FakeContainer]:
        return [self._container] if self._container else []


class _FakeClient:
    def __init__(self, container: _FakeContainer | None = None) -> None:
        self.containers = _FakeContainers(container)


def test_create_container_writes_labels_and_returns_port(monkeypatch: pytest.MonkeyPatch) -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(container)
    # create_container narrows the run() result with isinstance(_, Container);
    # point that check at the fake so the stub is accepted.
    monkeypatch.setattr(podman_ops, "Container", _FakeContainer)
    monkeypatch.setattr(podman_ops, "_allocate_host_port", lambda: 49207)

    info = podman_ops.create_container(
        client,
        cs_id="abc",
        image="img",
        repo="owner/name",
        workspace="default",
        user="dev",
        workspace_host_dir="/host/ws",
    )

    assert info.port == 49207
    run_kwargs = client.containers.runs[0]
    assert run_kwargs["name"] == "codespace-abc"
    assert run_kwargs["network_mode"] == "host"
    assert run_kwargs["cap_add"] == ["NET_RAW"]
    assert run_kwargs["pids_limit"] == -1
    assert run_kwargs["ulimits"] == [{"Name": "memlock", "Soft": -1, "Hard": -1}]
    assert run_kwargs["environment"] == {"SSHD_PORT": "49207"}
    assert run_kwargs["labels"][shared.LABEL_REPO] == "owner/name"
    assert run_kwargs["labels"][shared.LABEL_PORT] == "49207"
    assert run_kwargs["mounts"][0]["source"] == "/host/ws"


def test_ensure_workspace_dir_creates_missing_parents(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "missing" / "workspace"
    podman_ops.ensure_workspace_dir(str(workspace_dir))
    assert workspace_dir.is_dir()


def test_inject_credentials_chowns_and_puts_archive() -> None:
    container = _ExecContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(container)

    podman_ops.inject_credentials(
        client,
        cs_id="abc",
        user="dev",
        private_key="PRIV",
        login_pubkey="ssh-ed25519 LOGIN",
    )

    # workspace chown (root) happened before archive, ~/.ssh chown after.
    assert (["chown", "-R", "dev:dev", "/workspace"], "0") in container.execs
    assert container.archives  # credentials were written via put_archive
    path, data = container.archives[0]
    assert path == "/home/dev/.ssh"
    names = _tar_names(data)
    assert set(names) == {"repo_id_ed25519", "config", "authorized_keys"}


def test_inject_credentials_uses_stdout_from_multiplexed_home_output() -> None:
    output = _exec_frame(1, b"/home/x") + _exec_frame(
        2, b"[conmon:d]: exec with attach is waiting \x81"
    )
    container = _ExecContainer(labels={shared.LABEL_ID: "abc"}, home=output)
    client = _FakeClient(container)

    podman_ops.inject_credentials(
        client,
        cs_id="abc",
        user="x",
        private_key="PRIV",
        login_pubkey="ssh-ed25519 LOGIN",
    )

    assert container.archives[0][0] == "/home/x/.ssh"


def test_inject_credentials_with_extra_repo_writes_alias_and_gitconfig() -> None:
    container = _ExecContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(container)

    podman_ops.inject_credentials(
        client,
        cs_id="abc",
        user="dev",
        private_key="PRIV",
        login_pubkey="ssh-ed25519 LOGIN",
        extra_keys=[("owner/dotfiles", "EXTRA_PRIV")],
    )

    alias = shared.extra_repo_ssh_alias("owner/dotfiles")
    # ~/.ssh archive carries the extra key file + main key + config + authkeys.
    ssh_archive = next(d for p, d in container.archives if p == "/home/dev/.ssh")
    assert f"repo_{alias}" in _tar_names(ssh_archive)
    # ssh config pins the alias to its own key.
    config_bytes = _tar_member(ssh_archive, "config")
    assert f"Host {alias}" in config_bytes.decode()
    assert f"IdentityFile ~/.ssh/repo_{alias}" in config_bytes.decode()
    # ~/.gitconfig carries the insteadOf rewrite for transparent clones.
    git_archive = next(d for p, d in container.archives if p == "/home/dev")
    gitconfig = _tar_member(git_archive, ".gitconfig").decode()
    assert f"git@{alias}:owner/dotfiles" in gitconfig
    assert "insteadOf = git@github.com:owner/dotfiles" in gitconfig


def test_clone_repo_clones_into_repo_name_directory() -> None:
    container = _ExecContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(container)

    podman_ops.clone_repo(client, cs_id="abc", user="dev", repo="owner/name")

    cmd, user = container.execs[-1]
    assert user == "dev"
    assert cmd[:2] == ["sh", "-c"]
    assert cmd[-2:] == ["owner/name", "/workspace/name"]
    assert 'git clone "git@github.com:$repo" "$target"' in cmd[2]


def test_get_container_returns_none_when_absent() -> None:
    client = _FakeClient(None)
    assert podman_ops.get_container(client, "missing") is None


def test_list_containers_filters_by_label() -> None:
    labeled = _FakeContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(labeled)
    assert podman_ops.list_containers(client) == [labeled]


def test_find_container_by_workspace_matches_repo_and_workspace() -> None:
    container = _FakeContainer(
        labels={
            shared.LABEL_ID: "abc",
            shared.LABEL_REPO: "owner/name",
            shared.LABEL_WORKSPACE: "default",
        }
    )
    client = _FakeClient(container)

    assert podman_ops.find_container_by_workspace(client, "owner/name", "default") is container
    assert podman_ops.find_container_by_workspace(client, "owner/name", "other") is None


def test_pull_image_delegates_to_podman_images() -> None:
    client = _FakeClient(_FakeContainer(labels={}))
    pulled: list[str] = []
    client.images = type("_Images", (), {"pull": lambda self, image: pulled.append(image)})()

    podman_ops.pull_image(client, "codespace/dev:latest")

    assert pulled == ["codespace/dev:latest"]


def test_purge_workspace_runs_helper_container() -> None:
    client = _FakeClient(_FakeContainer(labels={}))
    podman_ops.purge_workspace(client, "/host/ws")
    run = client.containers.runs[0]
    assert run["mounts"][0]["source"] == "/host/ws"
    assert run["remove"] is True


def _tar_names(data: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        return tar.getnames()


def _tar_member(data: bytes, name: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        extracted = tar.extractfile(name)
        assert extracted is not None
        return extracted.read()


def _exec_frame(stream: int, payload: bytes) -> bytes:
    return bytes([stream, 0, 0, 0]) + len(payload).to_bytes(4, "big") + payload
