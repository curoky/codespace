import subprocess

import pytest

from codespace.client.config import AgentProfile
from codespace.client.service import SshHttpTunnel, _agent_target_host, _ssh_forward_target_host


def test_ssh_forward_target_host_wraps_ipv6_addresses() -> None:
    assert (
        _ssh_forward_target_host("2605:340:cd52:105:3634:f427:f62d:4143")
        == "[2605:340:cd52:105:3634:f427:f62d:4143]"
    )


def test_ssh_forward_target_host_leaves_non_ipv6_hosts_unchanged() -> None:
    assert _ssh_forward_target_host("127.0.0.1") == "127.0.0.1"
    assert _ssh_forward_target_host("agent.internal") == "agent.internal"


def test_agent_target_host_maps_ipv6_wildcard_to_loopback() -> None:
    assert _agent_target_host("::") == "127.0.0.1"


def test_ssh_http_tunnel_uses_distinct_proxy_host(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    class FakeProcess:
        def poll(self) -> None:
            return None

    def _popen(cmd: list[str], **kwargs: object) -> FakeProcess:
        commands.append(cmd)
        assert kwargs["stdout"] is subprocess.PIPE
        assert kwargs["stderr"] is subprocess.PIPE
        return FakeProcess()

    monkeypatch.setattr("codespace.client.service._free_local_port", lambda: 43210)
    monkeypatch.setattr("codespace.client.service._wait_for_agent", lambda _url: None)
    monkeypatch.setattr("codespace.client.service.subprocess.Popen", _popen)

    tunnel = SshHttpTunnel(
        AgentProfile(
            id="home",
            agent_url="http://127.0.0.1:8001",
            ssh_host="dev-container-host",
            ssh_proxy_host="bastion-host",
            ssh_proxy=True,
        )
    )

    assert tunnel.local_url == "http://127.0.0.1:43210"
    assert commands == [
        [
            "ssh",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=2",
            "-N",
            "-L",
            "127.0.0.1:43210:127.0.0.1:8001",
            "bastion-host",
        ]
    ]
