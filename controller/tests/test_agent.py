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
_S6_ROOT = Path(__file__).parents[2] / "images" / "dev" / "rootfs" / "etc" / "s6" / "s6-rc.d"


def _load_image_agent() -> ModuleType:
    sys.path.insert(0, str(_AGENT_ROOT))
    return importlib.import_module("codespace_agent")


image_agent = _load_image_agent()


def test_s6_generates_deploy_key_for_every_workspace_before_bootstrap() -> None:
    service = _S6_ROOT / "workspace-deploy-key"

    assert (service / "type").read_text(encoding="utf-8").strip() == "oneshot"
    assert (service / "dependencies.d" / "workspace-crypt").is_file()
    assert "/opt/codespace/bin/codespace-deploy-key" in (service / "up").read_text(encoding="utf-8")
    assert (_S6_ROOT / "workspace-bootstrap" / "dependencies.d" / "workspace-deploy-key").is_file()


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


class FakeRunFactory:
    def __init__(
        self,
        *,
        fail: str | None = None,
        repository: bool = True,
        head: bool = True,
        dirty: str = " M README.md\n",
        unpushed: str = "abc123 commit\n",
    ) -> None:
        self.fail = fail
        self.repository = repository
        self.head = head
        self.dirty = dirty
        self.unpushed = unpushed
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, kwargs))
        name = Path(command[0]).name
        if name == self.fail:
            raise subprocess.CalledProcessError(1, command, stderr="command failed")
        stdout = ""
        if command[-2:] == ["status", "--porcelain"]:
            stdout = self.dirty
        elif command[-1] == "--git-dir":
            if not self.repository:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="not a repository")
            stdout = ".git\n"
        elif command[-1] == "HEAD":
            if not self.head:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="unknown revision")
            stdout = "abc123\n"
        elif command[-1] == "--oneline":
            stdout = self.unpushed
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def _runner(factory: FakeRunFactory) -> object:
    return image_agent.CommandRunner(run_factory=factory)


def _wait_state(agent: object, state: str) -> object:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        status = agent.status()
        if status.state == state:
            return status
        time.sleep(0.01)
    raise AssertionError(f"agent did not reach {state!r}")


def _components(
    tmp_path: Path,
    *,
    request: object | None = None,
    factory: FakeRunFactory | None = None,
) -> tuple[object, object, FakeRunFactory]:
    active_request = request or _request()
    active_factory = factory or FakeRunFactory()
    runner = _runner(active_factory)
    deploy_public_key_path = tmp_path / "repo_id_ed25519.pub"
    provider_ready_path = tmp_path / "provider-ready"
    status_path = tmp_path / "status.json"
    deploy_public_key_path.write_text("ssh-ed25519 AAAAC3 test\n", encoding="utf-8")
    bootstrap = image_agent.WorkspaceBootstrap(
        active_request,
        runner=runner,
        deploy_public_key_path=deploy_public_key_path,
        provider_ready_path=provider_ready_path,
        status_path=status_path,
        provider_ready_poll_interval=0.01,
    )
    agent = image_agent.WorkspaceAgent(
        active_request,
        runner=runner,
        provider_ready_path=provider_ready_path,
        status_path=status_path,
    )
    return bootstrap, agent, active_factory


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


def test_s6_bootstrap_waits_for_provider_then_agent_reports_git_state(
    tmp_path: Path,
) -> None:
    bootstrap, workspace_agent, factory = _components(tmp_path)

    thread = threading.Thread(target=bootstrap.run, daemon=True)
    thread.start()
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
        "uncommitted": True,
        "detail": [" M README.md", "abc123 commit"],
    }
    commands = [Path(call[0][0]).name for call in factory.calls]
    assert commands[:2] == [
        "codespace-git-checkout",
        "codespace-workspace-open-path",
    ]
    assert commands[2:] == ["git", "git", "git", "git"]
    assert all(call[1]["user"] == 5230 for call in factory.calls)
    assert all(call[1]["group"] == 5230 for call in factory.calls)
    assert all(call[1]["env"]["HOME"] == "/home/x" for call in factory.calls)


def test_blank_bootstrap_runs_without_agent_calls(tmp_path: Path) -> None:
    request = _request(workspace_type="blank", clone_url=None)
    bootstrap, workspace_agent, factory = _components(tmp_path, request=request)

    status = bootstrap.run()

    assert status.state == "ready"
    assert workspace_agent.status().state == "ready"
    assert [Path(call[0][0]).name for call in factory.calls] == ["codespace-workspace-open-path"]
    with pytest.raises(image_agent.APIError, match="no Git state"):
        workspace_agent.git_state()


def test_bootstrap_failure_is_persisted_for_agent(tmp_path: Path) -> None:
    factory = FakeRunFactory(fail="codespace-git-checkout")
    request = _request(workspace_type="git", clone_url="git@example:repo")
    bootstrap, workspace_agent, _ = _components(
        tmp_path,
        request=request,
        factory=factory,
    )

    status = bootstrap.run()

    assert status.state == "failed"
    assert workspace_agent.status() == status
    assert "codespace-git-checkout failed (1): command failed" in (status.error or "")


def test_bootstrap_rejects_empty_deploy_public_key(tmp_path: Path) -> None:
    bootstrap, workspace_agent, _ = _components(tmp_path)
    (tmp_path / "repo_id_ed25519.pub").write_text("", encoding="utf-8")

    status = bootstrap.run()

    assert status.state == "failed"
    assert workspace_agent.status() == status
    assert status.error == "deploy public key is empty"


def test_git_state_command_failure_maps_to_api_error(tmp_path: Path) -> None:
    factory = FakeRunFactory()
    request = _request(workspace_type="git", clone_url="git@example:repo")
    bootstrap, workspace_agent, _ = _components(
        tmp_path,
        request=request,
        factory=factory,
    )
    bootstrap.run()
    factory.fail = "git"

    with pytest.raises(image_agent.APIError, match=r"git failed \(1\)"):
        workspace_agent.git_state()


@pytest.mark.parametrize(
    ("factory", "expected"),
    [
        (
            FakeRunFactory(repository=False),
            {"unpushed": False, "uncommitted": False, "detail": []},
        ),
        (
            FakeRunFactory(head=False, dirty="", unpushed=""),
            {"unpushed": False, "uncommitted": False, "detail": []},
        ),
    ],
    ids=["missing-checkout", "empty-repository"],
)
def test_git_state_reports_missing_and_empty_repositories_as_clean(
    tmp_path: Path,
    factory: FakeRunFactory,
    expected: dict[str, object],
) -> None:
    request = _request(workspace_type="git", clone_url="git@example:repo")
    bootstrap, workspace_agent, _ = _components(
        tmp_path,
        request=request,
        factory=factory,
    )
    bootstrap.run()

    assert workspace_agent.git_state().model_dump() == expected


def test_git_state_caps_detail_at_twenty_lines(tmp_path: Path) -> None:
    dirty = "".join(f"?? file-{index}.txt\n" for index in range(25))
    factory = FakeRunFactory(dirty=dirty)
    request = _request(workspace_type="git", clone_url="git@example:repo")
    bootstrap, workspace_agent, _ = _components(
        tmp_path,
        request=request,
        factory=factory,
    )
    bootstrap.run()

    state = workspace_agent.git_state()

    assert state.uncommitted is True
    assert len(state.detail) == 20


def test_bootstrap_reuses_durable_provider_acknowledgement(tmp_path: Path) -> None:
    first_bootstrap, first_agent, _ = _components(tmp_path)
    first_thread = threading.Thread(target=first_bootstrap.run, daemon=True)
    first_thread.start()
    _wait_state(first_agent, "awaiting-provider")
    first_agent.provider_ready(_GENERATION)
    _wait_state(first_agent, "ready")
    first_thread.join(timeout=1)

    restarted_factory = FakeRunFactory()
    restarted_bootstrap, restarted_agent, _ = _components(
        tmp_path,
        factory=restarted_factory,
    )
    restarted_bootstrap.run()

    assert restarted_agent.status().state == "ready"
    assert (tmp_path / "provider-ready").read_text(encoding="utf-8") == f"{_GENERATION}\n"
    assert [Path(call[0][0]).name for call in restarted_factory.calls] == [
        "codespace-git-checkout",
        "codespace-workspace-open-path",
    ]


def test_agent_ignores_status_from_an_old_generation(tmp_path: Path) -> None:
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "generation": "b" * 32,
                "state": "ready",
                "public_key": None,
                "error": None,
            }
        ),
        encoding="utf-8",
    )
    _, workspace_agent, _ = _components(tmp_path)

    assert workspace_agent.status().state == "starting"


@contextmanager
def _running_server(tmp_path: Path) -> Iterator[Path]:
    socket_path = tmp_path / "agent.sock"
    bootstrap, workspace_agent, _ = _components(tmp_path)
    server, server_socket = image_agent.build_server(
        socket_path=socket_path,
        agent=workspace_agent,
    )
    server_thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [server_socket]},
        daemon=True,
    )
    bootstrap_thread = threading.Thread(target=bootstrap.run, daemon=True)
    server_thread.start()
    bootstrap_thread.start()
    try:
        yield socket_path
    finally:
        if workspace_agent.status().state == "awaiting-provider":
            workspace_agent.provider_ready(_GENERATION)
        bootstrap_thread.join(timeout=2)
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
        client = WorkspaceAgentClient(socket_path, _GENERATION)
        client.wait_for({"awaiting-provider"}, timeout=2)
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
    _, workspace_agent, _ = _components(
        tmp_path,
        request=_request(workspace_type="blank", clone_url=None),
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
