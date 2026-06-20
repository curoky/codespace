"""Tests for the fixed HTTP-over-UDS Workspace agent client."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from codespace.workspaces import agent


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> agent.WorkspaceAgentClient:
    monkeypatch.setattr(agent, "_UnixHTTPConnection", FakeConnection)
    return agent.WorkspaceAgentClient(tmp_path / "agent.sock")


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


@pytest.mark.parametrize(
    "payload",
    [
        {"state": "starting", "public_key": None, "error": None},
        {"state": "ready", "public_key": None, "error": None},
        {"state": "ready", "public_key": "ssh-ed25519 PUBLIC", "error": None},
        {"state": "awaiting-provider", "public_key": "ssh-ed25519 PUBLIC", "error": None},
        {"state": "failed", "public_key": None, "error": "checkout failed"},
    ],
)
def test_status_validates_fixed_response(
    client: agent.WorkspaceAgentClient,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    monkeypatch.setattr(
        FakeConnection,
        "response",
        SimpleNamespace(status=200, read=lambda _limit: json.dumps(payload).encode()),
    )

    status = client.status()

    assert status.model_dump() == payload


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"state": "unknown", "public_key": None, "error": None},
        {"state": "ready"},
        {"state": "ready", "public_key": None, "error": "unexpected error"},
        {"state": "ready", "public_key": None, "error": None, "extra": True},
        {"state": "awaiting-provider", "error": None},
        {"state": "awaiting-provider", "public_key": None, "error": None},
        {"state": "awaiting-provider", "public_key": "", "error": None},
        {"state": "awaiting-provider", "public_key": " \n", "error": None},
        {"state": "failed", "public_key": None},
        {"state": "failed", "public_key": None, "error": None},
        {"state": "failed", "public_key": None, "error": ""},
        {"state": "failed", "public_key": None, "error": " \n"},
    ],
)
def test_invalid_response_is_rejected(
    client: agent.WorkspaceAgentClient,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(agent.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        FakeConnection,
        "response",
        SimpleNamespace(status=200, read=lambda _limit: json.dumps(payload).encode()),
    )

    with pytest.raises(agent.AgentError, match="invalid status") as caught:
        client.wait_for("ready", timeout=1)

    assert isinstance(caught.value.__cause__, ValidationError)
    assert sleeps == []


def test_failed_agent_state_stops_waiting(
    client: agent.WorkspaceAgentClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"state": "failed", "public_key": None, "error": "checkout failed"}
    monkeypatch.setattr(
        FakeConnection,
        "response",
        SimpleNamespace(status=200, read=lambda _limit: json.dumps(payload).encode()),
    )

    with pytest.raises(agent.AgentError, match="checkout failed"):
        client.wait_for("ready", timeout=1)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"unpushed": False, "uncommitted": False},
        {"unpushed": False, "detail": []},
        {"uncommitted": False, "detail": []},
        {"unpushed": "false", "uncommitted": False, "detail": []},
        {"unpushed": 0, "uncommitted": False, "detail": []},
        {"unpushed": False, "uncommitted": None, "detail": []},
        {"unpushed": False, "uncommitted": False, "detail": None},
        {"unpushed": False, "uncommitted": False, "detail": [1]},
        {"unpushed": False, "uncommitted": False, "detail": [], "extra": True},
    ],
)
def test_invalid_git_state_is_not_treated_as_clean(
    client: agent.WorkspaceAgentClient,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    monkeypatch.setattr(
        FakeConnection,
        "response",
        SimpleNamespace(status=200, read=lambda _limit: json.dumps(payload).encode()),
    )

    with pytest.raises(agent.AgentError, match="invalid Git state") as caught:
        client.git_state()

    assert isinstance(caught.value.__cause__, ValidationError)


@pytest.mark.parametrize(
    "payload",
    [
        {"unpushed": False, "uncommitted": False, "detail": []},
        {"unpushed": True, "uncommitted": True, "detail": [" M file", "abc new commit"]},
    ],
)
def test_git_state_preserves_complete_response(
    client: agent.WorkspaceAgentClient,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    monkeypatch.setattr(
        FakeConnection,
        "response",
        SimpleNamespace(status=200, read=lambda _limit: json.dumps(payload).encode()),
    )

    assert client.git_state().model_dump() == payload


def test_http_error_reports_agent_detail(
    client: agent.WorkspaceAgentClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        FakeConnection,
        "response",
        SimpleNamespace(
            status=409,
            reason="Conflict",
            read=lambda _limit: b'{"detail":"agent state is starting"}',
        ),
    )

    with pytest.raises(agent.AgentError, match=r"failed \(409\): agent state is starting"):
        client.git_state()


@pytest.mark.parametrize("payload", [{}, {"error": "wrong schema"}, {"detail": ""}])
def test_malformed_http_error_is_rejected(
    client: agent.WorkspaceAgentClient,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    monkeypatch.setattr(
        FakeConnection,
        "response",
        SimpleNamespace(
            status=409, reason="Conflict", read=lambda _limit: json.dumps(payload).encode()
        ),
    )

    with pytest.raises(agent.AgentError, match="invalid error response"):
        client.git_state()


def test_wait_retries_socket_availability_and_bootstrap_progress(
    client: agent.WorkspaceAgentClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts: list[str] = []
    sleeps: list[float] = []
    responses = iter(
        [
            agent.AgentUnavailable("socket not ready"),
            agent.BootstrapStatus(state="starting", public_key=None, error=None),
            agent.ProviderStatus(state="awaiting-provider", public_key="PUBLIC", error=None),
        ]
    )

    def status() -> agent.AgentStatus:
        attempts.append("status")
        response = next(responses)
        if isinstance(response, agent.AgentUnavailable):
            raise response
        return response

    monkeypatch.setattr(client, "status", status)
    monkeypatch.setattr(agent.time, "sleep", sleeps.append)

    ready = client.wait_for("awaiting-provider", timeout=1)

    assert ready.public_key == "PUBLIC"
    assert len(attempts) == 3
    assert len(sleeps) == 2


def test_wait_remains_bounded(
    client: agent.WorkspaceAgentClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = iter([0.0, 0.0, 2.0])
    sleeps: list[float] = []
    monkeypatch.setattr(agent.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(agent.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        client,
        "status",
        lambda: agent.BootstrapStatus(state="starting", public_key=None, error=None),
    )

    with pytest.raises(agent.AgentUnavailable, match="did not reach 'ready'"):
        client.wait_for("ready", timeout=1)

    assert len(sleeps) == 1


@pytest.fixture
def image_agent(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "platform/container/workspace/agent/agent.py"
    spec = importlib.util.spec_from_file_location("workspace_image_agent", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("source", ["empty", "git", "github"])
@pytest.mark.parametrize("fail", [False, True])
def test_image_bootstrap_responses_satisfy_client_contract(
    image_agent: ModuleType,
    client: agent.WorkspaceAgentClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: str,
    fail: bool,
) -> None:
    key = tmp_path / "key.pub"
    key.write_text("ssh-ed25519 PUBLIC\n")
    authorized = tmp_path / "provider-ready"
    worker = image_agent.WorkspaceAgent(
        source,
        "/workspace/repo",
        "/workspace/repo",
        clone_url=None if source == "empty" else "git@example.com:owner/repo.git",
        deploy_public_key_path=key,
        provider_ready_path=authorized,
    )
    states: list[str] = []
    with TestClient(image_agent.create_app(worker)) as server:

        def read_status() -> None:
            response = server.get("/status")
            assert response.status_code == 200
            monkeypatch.setattr(
                FakeConnection,
                "response",
                SimpleNamespace(status=response.status_code, read=lambda _limit: response.content),
            )
            states.append(client.status().state)

        def authorize(_interval: float) -> None:
            read_status()
            authorized.touch()

        def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if fail:
                raise RuntimeError("checkout failed")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        worker._sleep = authorize
        monkeypatch.setattr(image_agent, "run_command", run)
        read_status()
        worker.run_bootstrap()
        read_status()

    assert states == [
        "starting",
        *(["awaiting-provider"] if source == "github" else []),
        "failed" if fail else "ready",
    ]


def test_image_git_and_error_responses_satisfy_client_contract(
    image_agent: ModuleType,
    client: agent.WorkspaceAgentClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = image_agent.WorkspaceAgent(
        "git", "/workspace/repo", "/workspace/repo", clone_url="git@example.com:owner/repo.git"
    )
    monkeypatch.setattr(
        image_agent,
        "run_command",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
    )
    with TestClient(image_agent.create_app(worker)) as server:
        response = server.get("/git-state")
        assert response.status_code == 409
        monkeypatch.setattr(
            FakeConnection,
            "response",
            SimpleNamespace(status=response.status_code, read=lambda _limit: response.content),
        )
        with pytest.raises(agent.AgentError, match="agent state is 'starting'"):
            client.git_state()

        worker.run_bootstrap()
        response = server.get("/git-state")
        assert response.status_code == 200
        monkeypatch.setattr(
            FakeConnection,
            "response",
            SimpleNamespace(status=response.status_code, read=lambda _limit: response.content),
        )
        assert client.git_state().model_dump() == {
            "unpushed": False,
            "uncommitted": False,
            "detail": [],
        }
