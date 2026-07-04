"""Tests for the pure helpers in podman_ops (no podman service needed)."""

import io
import tarfile

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
        self.id = "deadbeef"
        self.name = labels.get(shared.LABEL_ID, "")

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
    assert cs.deploy_public_key is None
    assert cs.workspace_dir == shared.workspace_dir_name("owner/name", "default")


def test_to_codespace_tolerates_missing_port() -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "x"}, ports={})
    cs = podman_ops.to_codespace(container)
    assert cs.port == 0
