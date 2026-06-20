"""Tests for ControlPlane aggregation and Host failure isolation."""

import ast
from pathlib import Path

import pytest

from codespace.config import Config
from codespace.control import ControlPlane, HostFailure, HostInventory
from codespace.runtime.transport import SSHRoute, TransportError
from codespace.services.models import Service
from codespace.web.dashboard import build


class FakeTransport:
    def ssh_route(self, host: str) -> SSHRoute:
        return SSHRoute(host=host)

    def close(self) -> None:
        return None


def test_dashboard_isolates_host_failure(config: Config) -> None:
    control = ControlPlane(config, transport=FakeTransport())  # type: ignore[arg-type]
    control.workspaces.inventory = lambda host: (
        [] if host == "home" else (_ for _ in ()).throw(TransportError("SSH down"))
    )
    control.services.inventory = lambda _host: []

    dashboard = build(control)

    assert [host.status for host in dashboard.hosts] == ["online", "offline"]
    assert dashboard.hosts[1].error == "TransportError: SSH down"
    assert dashboard.hosts[1].workspace_count is None
    assert [project.id for project in dashboard.projects] == [
        "codespace",
        "service-api",
        "scratch",
        "personal",
    ]


def test_dashboard_keeps_actual_metadata_when_config_changes(config: Config) -> None:
    workspace = config.workspace_spec("codespace", "home", "debug").to_workspace(
        "workspace-id", status="running"
    )
    service = Service(
        service="support",
        host="home",
        image="support:deployed",
        container_id="service-id",
        status="running",
    )
    data = config.model_dump()
    data["projects"]["codespace"]["open_path"] = "/workspace/changed"
    data["project_defaults"]["tunnel_ports"] = [8005]
    data["projects"]["scratch"]["tunnel_ports"] = []
    data["services"]["support"]["image"] = "support:desired"
    control = ControlPlane(Config.model_validate(data), transport=FakeTransport())  # type: ignore[arg-type]
    control.workspaces.inventory = lambda host: [workspace] if host == "home" else []
    control.services.inventory = lambda host: [service] if host == "home" else []

    dashboard = build(control)

    assert "/workspace/codespace?" in dashboard.workspaces[0].trae_url
    assert dashboard.projects[0].tunnel_ports == [8005]
    assert dashboard.projects[2].tunnel_ports == []
    assert dashboard.services[0].hosts[0].desired_image == "support:desired"
    assert dashboard.services[0].hosts[0].container == service
    assert dashboard.services[1].hosts[0].container is None


@pytest.mark.parametrize("error", [KeyError("codespace.image"), RuntimeError("invalid metadata")])
def test_inventory_errors_are_not_classified_as_offline(config: Config, error: Exception) -> None:
    control = ControlPlane(config, transport=FakeTransport())  # type: ignore[arg-type]

    def inventory(host: str) -> list[object]:
        if host == "office":
            raise error
        return []

    control.workspaces.inventory = inventory  # type: ignore[assignment]
    control.services.inventory = lambda _host: []

    inventories = control.inventory()
    assert isinstance(inventories["home"], HostInventory)
    failure = inventories["office"]
    assert isinstance(failure, HostFailure)
    assert failure.status == "error"
    assert type(error).__name__ in failure.error
    dashboard = build(control)
    assert dashboard.hosts[1].status == "error"
    assert dashboard.hosts[1].workspace_count is None


def test_control_has_no_web_dependency() -> None:
    tree = ast.parse(Path("src/codespace/control.py").read_text())
    imports = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]
    assert not any(module.startswith("codespace.web") for module in imports)
