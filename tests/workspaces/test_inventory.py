"""Tests for Workspace inventory state."""

from types import SimpleNamespace

import pytest

from codespace.workspaces import inventory
from codespace.workspaces.models import WORKSPACE_CIPHER_MOUNT, WORKSPACE_MOUNT


def _container(workspace_mounts: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        id="container-id",
        labels={
            "codespace.kind": "workspace",
            "codespace.project": "codespace",
            "codespace.workspace": "debug",
            "codespace.source": "github",
            "codespace.repository": "curoky/codespace",
            "codespace.image": "workspace:latest",
            "codespace.platform": "native",
            "codespace.ssh-port": "22000",
        },
        attrs={
            "State": {"Status": "running"},
            "Mounts": [*workspace_mounts, "/upload", "/cache"],
        },
    )


@pytest.mark.parametrize(
    ("mount", "expected"),
    [(WORKSPACE_CIPHER_MOUNT, True), (WORKSPACE_MOUNT, False)],
)
def test_read_workspace_reports_container_encryption(mount: str, expected: bool) -> None:
    workspace = inventory.read_workspace(_container([mount]), "home")  # type: ignore[arg-type]

    assert workspace.encrypted is expected


@pytest.mark.parametrize("mounts", [[], [WORKSPACE_MOUNT, WORKSPACE_CIPHER_MOUNT]])
def test_read_workspace_rejects_ambiguous_workspace_mounts(mounts: list[str]) -> None:
    with pytest.raises(ValueError, match="must mount exactly one"):
        inventory.read_workspace(_container(mounts), "home")  # type: ignore[arg-type]
