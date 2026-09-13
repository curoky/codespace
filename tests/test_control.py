"""Tests for ControlPlane aggregation and Host failure isolation."""

import pytest

from codespace import control as control_module
from codespace.config import Config
from codespace.control import ControlPlane, HostFailure, HostInventory
from codespace.runtime.transport import SSHRoute, TransportError
from codespace.services import Service
from codespace.web.dashboard import build


class FakeTransport:
    def client(self, _host: str) -> object:
        return object()

    def ssh_route(self, host: str) -> SSHRoute:
        return SSHRoute(host=host)

    def close(self) -> None:
        return None


def test_dashboard_isolates_host_failure(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    control = ControlPlane(config, transport=FakeTransport())  # type: ignore[arg-type]
    monkeypatch.setattr(
        control_module.workspaces,
        "list_workspaces",
        lambda _client, host: (
            [] if host == "home" else (_ for _ in ()).throw(TransportError("SSH down"))
        ),
    )
    monkeypatch.setattr(control_module.services, "list_services", lambda *_args: [])

    dashboard = build(control)

    hosts = {host["id"]: host for host in dashboard["hosts"]}
    assert hosts["home"]["status"] == "online"
    assert hosts["office"]["status"] == "offline"
    assert hosts["office"]["error"] == "TransportError: SSH down"
    assert hosts["office"]["workspace_count"] is None
    assert {project["id"] for project in dashboard["projects"]} == set(config.projects)


def test_dashboard_keeps_actual_metadata_when_config_changes(
    config: Config, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    data["services"]["support"]["container"]["image"] = "support:desired"
    data["services"]["support"]["tunnel_ports"] = [8080, 8008]
    data["services"]["support"]["container"]["ports"] = [
        {"target": 8080, "published": 8110, "host_ip": "127.0.0.1"}
    ]
    control = ControlPlane(Config.model_validate(data), transport=FakeTransport())  # type: ignore[arg-type]
    monkeypatch.setattr(
        control_module.workspaces,
        "list_workspaces",
        lambda _client, host: [workspace] if host == "home" else [],
    )
    monkeypatch.setattr(
        control_module.services,
        "list_services",
        lambda _client, host: [service] if host == "home" else [],
    )

    dashboard = build(control)

    workspaces = {
        (item["project"], item["workspace"], item["host"]): item for item in dashboard["workspaces"]
    }
    projects = {item["id"]: item for item in dashboard["projects"]}
    services = {item["id"]: item for item in dashboard["services"]}
    assert "/workspace/codespace?" in workspaces[("codespace", "debug", "home")]["trae_url"]
    assert projects["codespace"]["tunnel_ports"] == [8005]
    assert projects["scratch"]["tunnel_ports"] == []
    support_host = services["support"]["hosts"][0]
    assert support_host["desired_image"] == "support:desired"
    assert support_host["tunnel_ports"] == [8080, 8008]
    assert support_host["container"] == service
    assert services["vllm"]["hosts"][0]["container"] is None


@pytest.mark.parametrize("error", [KeyError("codespace.image"), RuntimeError("invalid metadata")])
def test_inventory_errors_are_not_classified_as_offline(
    config: Config, error: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    control = ControlPlane(config, transport=FakeTransport())  # type: ignore[arg-type]

    def inventory(_client: object, host: str) -> list[object]:
        if host == "office":
            raise error
        return []

    monkeypatch.setattr(control_module.workspaces, "list_workspaces", inventory)
    monkeypatch.setattr(control_module.services, "list_services", lambda *_args: [])

    inventories = control.inventory()
    assert isinstance(inventories["home"], HostInventory)
    failure = inventories["office"]
    assert isinstance(failure, HostFailure)
    assert failure.status == "error"
    assert type(error).__name__ in failure.error
    dashboard = build(control)
    hosts = {host["id"]: host for host in dashboard["hosts"]}
    assert hosts["office"]["status"] == "error"
    assert hosts["office"]["workspace_count"] is None
