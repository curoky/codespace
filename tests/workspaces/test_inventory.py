"""Tests for Workspace inventory state."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from codespace.config import Config
from codespace.workspaces import inventory


def _container(encrypted: str) -> SimpleNamespace:
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
            "codespace.open-path": "/workspace/codespace",
            "codespace.encrypted": encrypted,
        },
        attrs={"State": "running"},
    )


@pytest.mark.parametrize(
    ("encrypted", "expected"),
    [("true", True), ("false", False)],
)
def test_read_workspace_uses_only_labels(encrypted: str, expected: bool) -> None:
    workspace = inventory.read_workspace(_container(encrypted), "home")  # type: ignore[arg-type]

    assert workspace.encrypted is expected
    assert workspace.open_path == "/workspace/codespace"
    assert workspace.status == "running"


@pytest.mark.parametrize("label", ["codespace.open-path", "codespace.encrypted"])
def test_read_workspace_requires_metadata(label: str) -> None:
    container = _container("false")
    del container.labels[label]

    with pytest.raises(KeyError, match=label):
        inventory.read_workspace(container, "home")  # type: ignore[arg-type]


def test_read_workspace_rejects_invalid_encryption_label() -> None:
    with pytest.raises(KeyError):
        inventory.read_workspace(_container("invalid"), "home")  # type: ignore[arg-type]


def test_read_workspace_rejects_escaping_open_path() -> None:
    container = _container("false")
    container.labels["codespace.open-path"] = "/workspace/../etc"

    with pytest.raises(ValidationError, match="must not contain"):
        inventory.read_workspace(container, "home")  # type: ignore[arg-type]


@pytest.mark.parametrize("project", ["codespace", "service-api", "scratch", "personal"])
def test_created_labels_round_trip_inventory(config: Config, project: str) -> None:
    host = config.project_hosts(project)[0]
    spec = config.workspace_spec(project, host, "debug")
    container = SimpleNamespace(id="container-id", labels=spec.labels(), attrs={"State": "running"})

    assert inventory.read_workspace(container, host) == spec.to_workspace(  # type: ignore[arg-type]
        "container-id", status="running"
    )
    assert inventory.read_workspace(container, host).source == config.projects[project].source  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "labels",
    [
        {"codespace.source": "github"},
        {"codespace.source": "git"},
        {"codespace.source": "unknown"},
        {"codespace.source": "empty", "codespace.repository": "owner/repo"},
        {"codespace.source": "github", "codespace.repository": "invalid"},
    ],
)
def test_inventory_rejects_incomplete_or_mismatched_sources(labels: dict[str, str]) -> None:
    container = _container("false")
    del container.labels["codespace.repository"]
    container.labels.update(labels)

    with pytest.raises(ValidationError):
        inventory.read_workspace(container, "home")  # type: ignore[arg-type]
