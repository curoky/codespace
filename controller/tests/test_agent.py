"""Tests for the controller client and in-image workspace agent contract."""

from __future__ import annotations

import http.client
import importlib
import json
import socket
import stat
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError

from controller.agent import AgentError, WorkspaceAgentClient, WorkspaceAgentRequest

_GENERATION = "a" * 32
_AGENT_ROOT = Path(__file__).parents[2] / "images" / "dev" / "rootfs" / "opt" / "codespace"


def _load_image_agent() -> ModuleType:
    sys.path.insert(0, str(_AGENT_ROOT))
    return importlib.import_module("codespace_agent")


image_agent = _load_image_agent()


def _request(
    *,
    workspace_type: str = "repo",
    clone_url: str | None = "git@github.com:curoky/devspace.git",
) -> object:
    return image_agent.AgentRequest(
        generation=_GENERATION,
        workspace_type=workspace_type,
        clone_url=clone_url,
        clone_path="/workspace/devspace" if workspace_type != "blank" else "/workspace",
        open_path="/workspace/devspace" if workspace_type != "blank" else "/workspace",
    )


class FakeRunner:
    def __init__(self, *, fail: str | None = None) -> None:
        self.fail = fail
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, kwargs))
        name = Path(command[0]).name
        if name == self.fail:
            raise subprocess.CalledProcessError(1, command, stderr="helper failed")
        stdout = ""
        if name == "codespace-deploy-key":
            stdout = '{"public_key":"ssh-ed25519 AAAAC3 test"}'
        elif name == "codespace-workspace-state":
            stdout = '{"unpushed":true,"uncommitted":false,"detail":["abc commit"]}'
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def _wait_state(agent: object, state: str) -> object:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        status = agent.status()
        if status.state == state:
            return status
        time.sleep(0.01)
    raise AssertionError(f"agent did not reach {state!r}")


def test_request_models_reject_invalid_workspace_contract(tmp_path: Path) -> None:
    request_path = tmp_path / "request.json"
    request_path.write_text(
        json.dumps(
            {
                "generation": _GENERATION,
                "workspace_type": "blank",
                "clone_url": "git@example:repo",
                "clone_path": "/workspace",
                "open_path": "/workspace",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(image_agent.RequestError, match="must not define clone_url"):
        image_agent.AgentRequest.load(request_path)
    with pytest.raises(ValidationError, match="must not define clone_url"):
        WorkspaceAgentRequest(
            generation=_GENERATION,
            workspace_type="blank",
            clone_url="git@example:repo",
            clone_path="/workspace",
            open_path="/workspace",
        )


def test_repo_agent_waits_for_provider_then_bootstraps_and_reports_git_state(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    workspace_agent = image_agent.WorkspaceAgent(
        _request(),
        run_factory=runner,
        provider_ready_path=tmp_path / "provider-ready",
    )

    thread = workspace_agent.start()
    waiting = _wait_state(workspace_agent, "awaiting-provider")

    assert waiting.public_key == "ssh-ed25519 AAAAC3 test"
    with pytest.raises(image_agent.APIError, match="generation does not match"):
        workspace_agent.provider_ready("b" * 32)

    workspace_agent.provider_ready(_GENERATION)
    _wait_state(workspace_agent, "ready")
    state = workspace_agent.git_state()
    thread.join(timeout=1)

    assert state.model_dump() == {
        "unpushed": True,
        "uncommitted": False,
        "detail": ["abc commit"],
    }
    assert [Path(call[0][0]).name for call in runner.calls] == [
        "codespace-deploy-key",
        "codespace-git-checkout",
        "codespace-workspace-open-path",
        "codespace-workspace-state",
    ]
    assert all(call[1]["user"] == 5230 for call in runner.calls)
    assert all(call[1]["group"] == 5230 for call in runner.calls)
    assert all(call[1]["env"]["HOME"] == "/home/x" for call in runner.calls)


def test_blank_agent_only_prepares_open_path() -> None:
    runner = FakeRunner()
    workspace_agent = image_agent.WorkspaceAgent(
        _request(workspace_type="blank", clone_url=None),
        run_factory=runner,
    )

    thread = workspace_agent.start()
    _wait_state(workspace_agent, "ready")
    thread.join(timeout=1)

    assert [Path(call[0][0]).name for call in runner.calls] == ["codespace-workspace-open-path"]
    with pytest.raises(image_agent.APIError, match="no Git state"):
        workspace_agent.git_state()


def test_helper_failure_moves_agent_to_failed_state() -> None:
    workspace_agent = image_agent.WorkspaceAgent(
        _request(workspace_type="git", clone_url="git@example:repo"),
        run_factory=FakeRunner(fail="codespace-git-checkout"),
    )

    thread = workspace_agent.start()
    status = _wait_state(workspace_agent, "failed")
    thread.join(timeout=1)

    assert "codespace-git-checkout failed (1): helper failed" in status.error


def test_git_state_helper_failure_maps_to_api_error() -> None:
    runner = FakeRunner()
    workspace_agent = image_agent.WorkspaceAgent(
        _request(workspace_type="git", clone_url="git@example:repo"),
        run_factory=runner,
    )
    thread = workspace_agent.start()
    _wait_state(workspace_agent, "ready")
    thread.join(timeout=1)
    runner.fail = "codespace-workspace-state"

    with pytest.raises(image_agent.APIError, match=r"codespace-workspace-state failed \(1\)"):
        workspace_agent.git_state()


def test_repo_agent_reuses_durable_provider_acknowledgement(tmp_path: Path) -> None:
    acknowledgement = tmp_path / "provider-ready"
    first = image_agent.WorkspaceAgent(
        _request(),
        run_factory=FakeRunner(),
        provider_ready_path=acknowledgement,
    )
    first_thread = first.start()
    _wait_state(first, "awaiting-provider")
    first.provider_ready(_GENERATION)
    _wait_state(first, "ready")
    first_thread.join(timeout=1)

    restarted_runner = FakeRunner()
    restarted = image_agent.WorkspaceAgent(
        _request(),
        run_factory=restarted_runner,
        provider_ready_path=acknowledgement,
    )
    restarted_thread = restarted.start()
    _wait_state(restarted, "ready")
    restarted_thread.join(timeout=1)

    assert acknowledgement.read_text(encoding="utf-8") == f"{_GENERATION}\n"
    assert [Path(call[0][0]).name for call in restarted_runner.calls] == [
        "codespace-deploy-key",
        "codespace-git-checkout",
        "codespace-workspace-open-path",
    ]


@contextmanager
def _running_server(tmp_path: Path) -> Iterator[Path]:
    socket_path = tmp_path / "agent.sock"
    workspace_agent = image_agent.WorkspaceAgent(
        _request(),
        run_factory=FakeRunner(),
        provider_ready_path=tmp_path / "provider-ready",
    )
    server, server_socket = image_agent.build_server(socket_path=socket_path, agent=workspace_agent)
    server_thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [server_socket]},
        daemon=True,
    )
    server_thread.start()
    workspace_agent.start()
    try:
        yield socket_path
    finally:
        server.should_exit = True
        server_thread.join(timeout=2)
        server_socket.close()
        socket_path.unlink(missing_ok=True)


def test_controller_client_completes_repo_handshake_over_uds(tmp_path: Path) -> None:
    with _running_server(tmp_path) as socket_path:
        client = WorkspaceAgentClient(socket_path, _GENERATION)

        status = client.wait_for({"awaiting-provider"}, timeout=2)
        acknowledged = client.provider_ready()
        ready = client.wait_for({"ready"}, timeout=2)
        state = client.git_state()

        assert status.public_key == "ssh-ed25519 AAAAC3 test"
        assert acknowledged.generation == _GENERATION
        assert ready.state == "ready"
        assert state.unpushed is True
        assert stat.S_IMODE(socket_path.stat().st_mode) == 0o666


def test_agent_http_rejects_generation_mismatch_and_unknown_route(tmp_path: Path) -> None:
    with _running_server(tmp_path) as socket_path:
        WorkspaceAgentClient(socket_path, _GENERATION).wait_for(
            {"awaiting-provider"},
            timeout=2,
        )
        wrong_client = WorkspaceAgentClient(socket_path, "b" * 32)

        with pytest.raises(AgentError, match=r"failed \(409\).*generation"):
            wrong_client.provider_ready()

        status, payload = _raw_request(socket_path, "GET", "/shell")
        assert status == 404
        assert payload == {"detail": "Not Found"}
        method_status, method_payload = _raw_request(socket_path, "PUT", "/status")
        assert method_status == 405
        assert method_payload == {"detail": "Method Not Allowed"}


def test_agent_server_replaces_stale_socket(tmp_path: Path) -> None:
    socket_path = tmp_path / "agent.sock"
    socket_path.write_text("stale", encoding="utf-8")
    workspace_agent = image_agent.WorkspaceAgent(
        _request(workspace_type="blank", clone_url=None),
        run_factory=FakeRunner(),
        provider_ready_path=tmp_path / "provider-ready",
    )

    server, server_socket = image_agent.build_server(
        socket_path=socket_path,
        agent=workspace_agent,
    )
    try:
        assert server.config.uds == str(socket_path)
        assert stat.S_ISSOCK(socket_path.stat().st_mode)
    finally:
        server_socket.close()
        socket_path.unlink(missing_ok=True)


def _raw_request(socket_path: Path, method: str, target: str) -> tuple[int, object]:
    class UnixConnection(http.client.HTTPConnection):
        def connect(self) -> None:
            connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.connect(str(socket_path))
            self.sock = connection

    connection = UnixConnection("localhost", timeout=2)
    try:
        connection.request(method, target)
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()
