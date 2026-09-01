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
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest

from controller.agent import WorkspaceAgentClient

_AGENT_ROOT = Path(__file__).parents[2] / "images" / "dev" / "rootfs" / "opt" / "codespace"
_S6_ROOT = Path(__file__).parents[2] / "images" / "dev" / "rootfs" / "etc" / "s6" / "s6-rc.d"


def _load_image_agent() -> ModuleType:
    sys.path.insert(0, str(_AGENT_ROOT))
    return importlib.import_module("workspace_agent")


image_agent = _load_image_agent()


def _config(*, workspace_type: str = "repo") -> object:
    return image_agent.AgentConfig(
        workspace_type=workspace_type,
        clone_path="/workspace/devspace" if workspace_type != "blank" else "/workspace",
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


def _agent(
    tmp_path: Path,
    *,
    workspace_type: str = "repo",
    factory: FakeRunFactory | None = None,
) -> tuple[object, FakeRunFactory]:
    active_factory = factory or FakeRunFactory()
    public_key = tmp_path / "repo_id_ed25519.pub"
    public_key.write_text("ssh-ed25519 AAAAC3 test\n", encoding="utf-8")
    agent = image_agent.WorkspaceAgent(
        _config(workspace_type=workspace_type),
        runner=image_agent.CommandRunner(run_factory=active_factory),
        deploy_public_key_path=public_key,
        provider_ready_path=tmp_path / "provider-ready",
        bootstrap_ready_path=tmp_path / "bootstrap.ready",
        bootstrap_failed_path=tmp_path / "bootstrap.failed",
        home_ready_path=tmp_path / "home.ready",
        home_failed_path=tmp_path / "home.failed",
    )
    return agent, active_factory


def test_s6_managed_bundle_runs_supervised_bootstrap_after_deploy_key() -> None:
    deploy_key = _S6_ROOT / "workspace-deploy-key"
    bootstrap = _S6_ROOT / "workspace-bootstrap"
    agent = _S6_ROOT / "workspace-agent"
    managed = _S6_ROOT / "managed-workspace"

    assert (deploy_key / "type").read_text(encoding="utf-8").strip() == "oneshot"
    assert (bootstrap / "type").read_text(encoding="utf-8").strip() == "longrun"
    assert (bootstrap / "dependencies.d" / "workspace-deploy-key").is_file()
    assert (agent / "dependencies.d" / "workspace-deploy-key").is_file()
    assert "codespace-workspace-bootstrap" in (bootstrap / "run").read_text(encoding="utf-8")
    assert (managed / "contents.d" / "user-final").is_file()
    assert (managed / "contents.d" / "workspace-bootstrap").is_file()
    assert not (_S6_ROOT / "user-base" / "contents.d" / "workspace-bootstrap").exists()


def test_s6_initializes_workspace_before_sshd_and_home() -> None:
    home = _S6_ROOT / "home-init"
    sshd = _S6_ROOT / "sshd"
    workspace_init = _S6_ROOT / "workspace-init"

    assert (home / "type").read_text(encoding="utf-8").strip() == "longrun"
    assert (home / "dependencies.d" / "workspace-crypt").is_file()
    assert (sshd / "dependencies.d" / "workspace-crypt").is_file()
    init_script = (workspace_init / "up").read_text(encoding="utf-8")
    for target in (
        "/home/x/.vscode-server",
        "/home/x/.trae",
        "/home/x/.trae-cn",
        "/home/x/.trae-server",
        "/home/x/.trae-cn-server",
    ):
        assert f"chown 5230:5230 {target}" in init_script
    assert not (_S6_ROOT / "home-links-init").exists()


def test_agent_config_loads_container_environment() -> None:
    config = image_agent.AgentConfig.load(
        {
            "CODESPACE_WORKSPACE_TYPE": "git",
            "CODESPACE_CLONE_PATH": "/workspace/devspace",
        }
    )

    assert config.workspace_type == "git"
    assert config.clone_path == "/workspace/devspace"

    with pytest.raises(image_agent.ConfigError, match="CODESPACE_WORKSPACE_TYPE"):
        image_agent.AgentConfig.load({})


def test_repo_status_waits_for_provider_and_exposes_public_key(tmp_path: Path) -> None:
    workspace_agent, _ = _agent(tmp_path)

    waiting = workspace_agent.status()
    assert waiting.state == "awaiting-provider"
    assert waiting.public_key == "ssh-ed25519 AAAAC3 test"

    (tmp_path / "provider-ready").write_text("", encoding="utf-8")
    assert workspace_agent.status().state == "starting"

    (tmp_path / "bootstrap.ready").write_text("ready\n", encoding="utf-8")
    assert workspace_agent.status().state == "starting"
    (tmp_path / "home.ready").write_text("ready\n", encoding="utf-8")
    assert workspace_agent.status().state == "ready"


def test_agent_reports_bootstrap_failure(tmp_path: Path) -> None:
    workspace_agent, _ = _agent(tmp_path, workspace_type="git")
    (tmp_path / "bootstrap.failed").write_text(
        "workspace bootstrap repository checkout failed (1)\n",
        encoding="utf-8",
    )

    status = workspace_agent.status()

    assert status.state == "failed"
    assert status.error == "workspace bootstrap repository checkout failed (1)"


def test_agent_reports_home_initialization_failure(tmp_path: Path) -> None:
    workspace_agent, _ = _agent(tmp_path, workspace_type="git")
    (tmp_path / "bootstrap.ready").write_text("ready\n", encoding="utf-8")
    (tmp_path / "home.failed").write_text(
        "home initialization failed (1)\n",
        encoding="utf-8",
    )

    status = workspace_agent.status()

    assert status.state == "failed"
    assert status.error == "home initialization failed (1)"


def test_blank_workspace_has_no_git_state(tmp_path: Path) -> None:
    workspace_agent, _ = _agent(tmp_path, workspace_type="blank")
    (tmp_path / "bootstrap.ready").write_text("ready\n", encoding="utf-8")
    (tmp_path / "home.ready").write_text("ready\n", encoding="utf-8")

    with pytest.raises(image_agent.APIError, match="no Git state"):
        workspace_agent.git_state()


def test_git_state_reports_dirty_and_unpushed_changes(tmp_path: Path) -> None:
    workspace_agent, factory = _agent(tmp_path, workspace_type="git")
    (tmp_path / "bootstrap.ready").write_text("ready\n", encoding="utf-8")
    (tmp_path / "home.ready").write_text("ready\n", encoding="utf-8")

    state = workspace_agent.git_state()

    assert state.model_dump() == {
        "unpushed": True,
        "uncommitted": True,
        "detail": [" M README.md", "abc123 commit"],
    }
    assert [Path(call[0][0]).name for call in factory.calls] == ["git", "git", "git", "git"]
    assert all(call[1]["user"] == 5230 for call in factory.calls)
    assert all(call[1]["group"] == 5230 for call in factory.calls)
    assert all(call[1]["env"]["HOME"] == "/home/x" for call in factory.calls)


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
    workspace_agent, _ = _agent(tmp_path, workspace_type="git", factory=factory)
    (tmp_path / "bootstrap.ready").write_text("ready\n", encoding="utf-8")
    (tmp_path / "home.ready").write_text("ready\n", encoding="utf-8")

    assert workspace_agent.git_state().model_dump() == expected


def test_git_state_caps_detail_at_twenty_lines(tmp_path: Path) -> None:
    dirty = "".join(f"?? file-{index}.txt\n" for index in range(25))
    workspace_agent, _ = _agent(
        tmp_path,
        workspace_type="git",
        factory=FakeRunFactory(dirty=dirty),
    )
    (tmp_path / "bootstrap.ready").write_text("ready\n", encoding="utf-8")
    (tmp_path / "home.ready").write_text("ready\n", encoding="utf-8")

    state = workspace_agent.git_state()

    assert state.uncommitted is True
    assert len(state.detail) == 20


@contextmanager
def _running_server(tmp_path: Path) -> Iterator[Path]:
    socket_path = tmp_path / "agent.sock"
    workspace_agent, _ = _agent(tmp_path)
    server, server_socket = image_agent.build_server(
        socket_path=socket_path,
        agent=workspace_agent,
    )
    server_thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [server_socket]},
        daemon=True,
    )
    server_thread.start()
    try:
        yield socket_path
    finally:
        server.should_exit = True
        server_thread.join(timeout=2)
        server_socket.close()
        socket_path.unlink(missing_ok=True)


def test_controller_client_completes_repo_handshake_over_uds(tmp_path: Path) -> None:
    with _running_server(tmp_path) as socket_path:
        client = WorkspaceAgentClient(socket_path)

        status = client.wait_for({"awaiting-provider"}, timeout=2)
        (tmp_path / "provider-ready").write_text("", encoding="utf-8")
        (tmp_path / "bootstrap.ready").write_text("ready\n", encoding="utf-8")
        (tmp_path / "home.ready").write_text("ready\n", encoding="utf-8")
        ready = client.wait_for({"ready"}, timeout=2)

        assert status.public_key == "ssh-ed25519 AAAAC3 test"
        assert ready.state == "ready"
        assert stat.S_IMODE(socket_path.stat().st_mode) == 0o666


def test_agent_http_rejects_unknown_route_and_method(tmp_path: Path) -> None:
    with _running_server(tmp_path) as socket_path:
        WorkspaceAgentClient(socket_path).wait_for({"awaiting-provider"}, timeout=2)
        status, payload = _raw_request(socket_path, "GET", "/shell")
        assert status == 404
        assert payload == {"detail": "Not Found"}
        method_status, method_payload = _raw_request(socket_path, "PUT", "/status")
        assert method_status == 405
        assert method_payload == {"detail": "Method Not Allowed"}


def test_agent_server_replaces_stale_socket(tmp_path: Path) -> None:
    socket_path = tmp_path / "agent.sock"
    socket_path.write_text("stale", encoding="utf-8")
    workspace_agent, _ = _agent(tmp_path, workspace_type="blank")

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
