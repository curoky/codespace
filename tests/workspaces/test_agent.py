"""Tests for the fixed HTTP-over-UDS Workspace agent client."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from codespace.workspaces import agent


class FakeConnection:
    response = SimpleNamespace(status=200, reason="OK", read=lambda _limit: b"{}")

    def __init__(self, _socket_path: Path, _timeout: float) -> None:
        self.requested: tuple[str, str] | None = None

    def request(self, method: str, target: str) -> None:
        self.requested = (method, target)

    def getresponse(self) -> object:
        return self.response

    def close(self) -> None:
        return None


def test_status_validates_fixed_response(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = {"state": "awaiting-provider", "public_key": "ssh-ed25519 PUBLIC"}
    FakeConnection.response = SimpleNamespace(
        status=200,
        reason="OK",
        read=lambda _limit: json.dumps(payload).encode(),
    )
    monkeypatch.setattr(agent, "_UnixHTTPConnection", FakeConnection)

    status = agent.WorkspaceAgentClient(tmp_path / "agent.sock").status()

    assert status.state == "awaiting-provider"
    assert status.public_key == "ssh-ed25519 PUBLIC"


def test_invalid_response_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeConnection.response = SimpleNamespace(
        status=200,
        reason="OK",
        read=lambda _limit: b'{"state":"unknown"}',
    )
    monkeypatch.setattr(agent, "_UnixHTTPConnection", FakeConnection)

    with pytest.raises(agent.AgentError, match="invalid status"):
        agent.WorkspaceAgentClient(tmp_path / "agent.sock").status()


def test_failed_agent_state_stops_waiting(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    client = agent.WorkspaceAgentClient(tmp_path / "agent.sock")
    monkeypatch.setattr(
        client,
        "status",
        lambda: agent.AgentStatus(state="failed", error="checkout failed"),
    )

    with pytest.raises(agent.AgentError, match="checkout failed"):
        client.wait_for({"ready"}, timeout=1)
