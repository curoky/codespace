"""Tests for container lifecycle, inventory and readiness probing.

These need no podman service: pure helpers run against fakes, and the SSH probe
runs against a real localhost socket.
"""

import socket
import threading
from contextlib import closing
from pathlib import Path

import pytest

from codespace import shared
from codespace.agent import containers


class _FakeContainer:
    """Minimal stand-in exposing the attributes the helpers read."""

    def __init__(self, labels: dict[str, str], status: str = "running") -> None:
        self.labels = labels
        self.status = status
        # Mirror podman's list-endpoint shape: a bare status string under State.
        self.attrs = {"State": status}
        self.id = "deadbeef"
        cs_id = labels.get(shared.LABEL_ID, "")
        self.name = shared.container_name(cs_id) if cs_id else ""

    def reload(self) -> None:
        pass


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

    def list(
        self, all: bool = False, filters: dict[str, str] | None = None
    ) -> list[_FakeContainer]:
        # Emulate podman's label filter: only return containers carrying the
        # requested label, matching the ``codespace.id`` scoping in production.
        if self._container is None:
            return []
        label = filters.get("label") if filters else None
        if label and label not in self._container.labels:
            return []
        return [self._container]


class _FakeClient:
    def __init__(self, container: _FakeContainer | None = None) -> None:
        self.containers = _FakeContainers(container)


def _labels(**overrides: str) -> dict[str, str]:
    labels = {
        shared.LABEL_ID: "abc123",
        shared.LABEL_REPO: "owner/name",
        shared.LABEL_PROVIDER: "github",
        shared.LABEL_TEMPLATE: "default",
        shared.LABEL_INSTANCE: "default",
        shared.LABEL_IMAGE: "codespace/dev:latest",
        shared.LABEL_PORT: "49207",
    }
    labels.update(overrides)
    return labels


def test_read_labels_reads_complete_state() -> None:
    labels = containers.read_labels(_FakeContainer(labels=_labels()))

    assert labels.cs_id == "abc123"
    assert labels.repo == "owner/name"
    assert labels.provider == "github"
    assert labels.template == "default"
    assert labels.instance == "default"
    assert labels.image == "codespace/dev:latest"
    assert labels.port == 49207


def test_read_labels_rejects_missing_required_value() -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "abc"})

    with pytest.raises(ValueError, match=r"missing required label codespace\.repo"):
        containers.read_labels(container)


def test_list_codespaces_maps_labels_and_port() -> None:
    container = _FakeContainer(labels=_labels())
    cs = containers.list_codespaces(_FakeClient(container))[0]
    assert cs.id == "abc123"
    assert cs.repo == "owner/name"
    assert cs.port == 49207
    assert cs.deploy_public_key is None
    assert cs.workspace_dir == shared.workspace_dir_name("owner/name", "default", "default")
    assert cs.status == "running"


def test_read_labels_rejects_invalid_provider_label() -> None:
    container = _FakeContainer(labels=_labels(**{shared.LABEL_PROVIDER: "bitbucket"}))

    with pytest.raises(ValueError, match="invalid git provider label"):
        containers.read_labels(container)


def test_read_labels_rejects_missing_state_label() -> None:
    labels = _labels()
    del labels[shared.LABEL_IMAGE]
    container = _FakeContainer(labels=labels)

    with pytest.raises(ValueError, match=r"missing required label codespace\.image"):
        containers.read_labels(container)


def test_read_labels_rejects_invalid_port_label() -> None:
    container = _FakeContainer(labels=_labels(**{shared.LABEL_PORT: "ssh"}))

    with pytest.raises(ValueError, match="invalid port label"):
        containers.read_labels(container)


# --- Orchestration tests with a fake podman client ---------------------------


def test_create_container_writes_labels_and_returns_port(monkeypatch: pytest.MonkeyPatch) -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(container)
    # create_container narrows the run() result with isinstance(_, Container);
    # point that check at the fake so the stub is accepted.
    monkeypatch.setattr(containers, "Container", _FakeContainer)
    monkeypatch.setattr(containers, "_allocate_host_port", lambda: 49207)

    info = containers.create_container(
        client,
        cs_id="abc",
        image="img",
        repo="owner/name",
        provider="github",
        template="default",
        instance="default",
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
    assert run_kwargs["labels"][shared.LABEL_TEMPLATE] == "default"
    assert run_kwargs["labels"][shared.LABEL_INSTANCE] == "default"
    assert run_kwargs["labels"][shared.LABEL_PORT] == "49207"
    assert run_kwargs["mounts"][0]["source"] == "/host/ws"
    assert run_kwargs["mounts"][1] == {
        "type": "bind",
        "source": "/etc/krb5.conf",
        "target": "/etc/krb5.conf",
        "read_only": True,
    }


def test_create_container_always_passes_host_krb5_conf_bind_to_podman(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(container)
    monkeypatch.setattr(containers, "Container", _FakeContainer)
    monkeypatch.setattr(containers, "_allocate_host_port", lambda: 49207)

    containers.create_container(
        client,
        cs_id="abc",
        image="img",
        repo="owner/name",
        provider="github",
        template="default",
        instance="default",
        workspace_host_dir="/host/ws",
    )

    run_kwargs = client.containers.runs[0]
    assert run_kwargs["mounts"] == [
        {
            "type": "bind",
            "source": "/host/ws",
            "target": shared.WORKSPACE_MOUNT,
        },
        {
            "type": "bind",
            "source": "/etc/krb5.conf",
            "target": "/etc/krb5.conf",
            "read_only": True,
        },
    ]


def test_ensure_workspace_dir_creates_missing_parents(tmp_path: Path) -> None:
    workspace_dir = tmp_path / "missing" / "workspace"
    containers.ensure_workspace_dir(str(workspace_dir))
    assert workspace_dir.is_dir()


def test_get_container_returns_none_when_absent() -> None:
    client = _FakeClient(None)
    assert containers.get_container(client, "missing") is None


def test_get_container_rejects_mismatched_id_label() -> None:
    container = _FakeContainer(labels=_labels())
    client = _FakeClient(container)

    with pytest.raises(ValueError, match="mismatched codespace id label"):
        containers.get_container(client, "different")


def test_list_codespaces_filters_by_prefix() -> None:
    labeled = _FakeContainer(labels=_labels())
    client = _FakeClient(labeled)
    assert [cs.id for cs in containers.list_codespaces(client)] == ["abc123"]


def test_list_codespaces_rejects_prefixed_container_without_complete_labels() -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(container)

    with pytest.raises(ValueError, match=r"missing required label codespace\.repo"):
        containers.list_codespaces(client)


def test_find_container_by_instance_matches_repo_template_and_instance() -> None:
    container = _FakeContainer(labels=_labels(**{shared.LABEL_PROVIDER: "gitlab"}))
    client = _FakeClient(container)

    assert (
        containers.find_container_by_instance(client, "owner/name", "default", "default")
        is container
    )
    assert containers.find_container_by_instance(client, "owner/name", "default", "other") is None


def test_pull_image_delegates_to_podman_images() -> None:
    client = _FakeClient(_FakeContainer(labels={}))
    pulled: list[str] = []
    client.images = type("_Images", (), {"pull": lambda self, image: pulled.append(image)})()

    containers.pull_image(client, "codespace/dev:latest")

    assert pulled == ["codespace/dev:latest"]


def test_purge_workspace_runs_helper_container() -> None:
    client = _FakeClient(_FakeContainer(labels={}))
    containers.purge_workspace(client, "/host/ws")
    run = client.containers.runs[0]
    assert run["mounts"][0]["source"] == "/host"
    assert run["mounts"][0]["target"] == "/workspaces"
    assert run["command"] == [
        "sh",
        "-c",
        'rm -rf -- "/workspaces/$1"',
        "purge-workspace",
        "ws",
    ]
    assert run["remove"] is True


@pytest.mark.parametrize("workspace_host_dir", ["/", ".", ""])
def test_purge_workspace_rejects_invalid_target(workspace_host_dir: str) -> None:
    client = _FakeClient(_FakeContainer(labels={}))
    with pytest.raises(ValueError, match="invalid workspace directory"):
        containers.purge_workspace(client, workspace_host_dir)
    assert client.containers.runs == []


# --- SSH readiness probe -----------------------------------------------------


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_wait_for_ssh_ready_accepts_listening_port(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    ready = threading.Event()

    def _server() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(1)
            ready.set()
            conn, _ = sock.accept()
            conn.close()

    thread = threading.Thread(target=_server)
    thread.start()
    ready.wait(timeout=1)
    monkeypatch.setattr(containers, "_READY_TIMEOUT_S", 0.2)
    monkeypatch.setattr(containers, "_READY_INTERVAL_S", 0.01)

    containers.wait_for_ssh_ready(port)

    thread.join(timeout=1)


def test_wait_for_ssh_ready_accepts_preauth_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    ready = threading.Event()

    def _server() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(1)
            ready.set()
            conn, _ = sock.accept()
            with conn:
                conn.sendall(b"Not allowed at this time\r\n")

    thread = threading.Thread(target=_server)
    thread.start()
    ready.wait(timeout=1)
    monkeypatch.setattr(containers, "_READY_TIMEOUT_S", 0.2)
    monkeypatch.setattr(containers, "_READY_INTERVAL_S", 0.01)

    containers.wait_for_ssh_ready(port)

    thread.join(timeout=1)


def test_wait_for_ssh_ready_rejects_closed_port(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    monkeypatch.setattr(containers, "_READY_TIMEOUT_S", 0.05)
    monkeypatch.setattr(containers, "_READY_INTERVAL_S", 0.01)

    with pytest.raises(RuntimeError, match="did not start listening"):
        containers.wait_for_ssh_ready(port)
