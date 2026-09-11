"""Tests for ControlPlane aggregation and Host failure isolation."""

from codespace.config import Config
from codespace.control import ControlPlane
from codespace.runtime.transport import SSHRoute
from codespace.services.models import Service


class FakeTransport:
    def ssh_route(self, host: str) -> SSHRoute:
        return SSHRoute(host=host)

    def close(self) -> None:
        return None


def test_dashboard_isolates_host_failure(config: Config) -> None:
    control = ControlPlane(config, transport=FakeTransport())  # type: ignore[arg-type]
    control.workspaces.inventory = lambda host: (
        [] if host == "home" else (_ for _ in ()).throw(RuntimeError("SSH down"))
    )
    control.services.inventory = lambda _host: []

    dashboard = control.dashboard()

    assert [host.status for host in dashboard.hosts] == ["online", "offline"]
    assert dashboard.hosts[1].error == "RuntimeError: SSH down"
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

    dashboard = control.dashboard()

    assert "/workspace/codespace?" in dashboard.workspaces[0].trae_url
    assert dashboard.projects[0].tunnel_ports == [8005]
    assert dashboard.projects[2].tunnel_ports == []
    assert dashboard.services[0].hosts[0].desired_image == "support:desired"
    assert dashboard.services[0].hosts[0].container == service
    assert dashboard.services[1].hosts[0].container is None
