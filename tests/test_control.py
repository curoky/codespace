"""Tests for ControlPlane aggregation and Host failure isolation."""

import pytest

from codespace.config import Config
from codespace.control import ControlPlane
from codespace.runtime.transport import SSHRoute
from codespace.workspaces import ssh


class FakeTransport:
    def ssh_route(self, host: str) -> SSHRoute:
        return SSHRoute(host=host)

    def close(self) -> None:
        return None


def test_dashboard_isolates_host_failure(
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ssh, "initialize", lambda _hosts: None)
    monkeypatch.setattr(ssh, "write_host", lambda *_args: None)
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
