"""Tests for Workspace SSH login probes."""

from __future__ import annotations

from pathlib import Path

import pytest

from codespace.runtime.transport import SSHRoute
from codespace.workspaces import ssh
from codespace.workspaces.models import (
    ProviderSource,
    Workspace,
)


def _workspace(name: str = "debug") -> Workspace:
    return Workspace(
        project="codespace",
        workspace=name,
        host="home",
        source=ProviderSource(type="github", repository="curoky/codespace"),
        image="workspace:latest",
        platform="native",
        open_path="/workspace/codespace",
        encrypted=False,
        container_id=f"container-{name}",
        status="running",
    )


def test_probe_uses_preprovisioned_config_and_existing_host_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []
    config = tmp_path / "config"
    monkeypatch.setattr(ssh, "SSH_CONFIG_PATH", config)
    monkeypatch.setattr(
        ssh.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    ssh.probe(_workspace(), SSHRoute(host="home", control_path=Path("/tmp/host.sock")))

    assert commands == [
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-F",
            str(config),
            "-o",
            f"Port={_workspace().ssh_host_port}",
            "-o",
            "ProxyCommand=ssh -o BatchMode=yes -o ControlPath=/tmp/host.sock -W %h:%p home",
            _workspace().ssh_alias,
            "true",
        ]
    ]
