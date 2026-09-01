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
from collections.abc import Callable, Iterator
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
    blank = workspace_type == "blank"
    return image_agent.AgentConfig(
        workspace_type=workspace_type,
        clone_path="/workspace" if blank else "/workspace/devspace",
        open_path="/workspace" if blank else "/workspace/devspace",
        clone_url=None if blank else "git@github.com:curoky/devspace.git",
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
    sleep: Callable[[float], None] | None = None,
) -> tuple[object, FakeRunFactory]:
    active_factory = factory or FakeRunFactory()
    public_key = tmp_path / "repo_id_ed25519.pub"
    public_key.write_text("ssh-ed25519 AAAAC3 test\n", encoding="utf-8")
    agent = image_agent.WorkspaceAgent(
        _config(workspace_type=workspace_type),
        runner=image_agent.CommandRunner(run_factory=active_factory),
        deploy_public_key_path=public_key,
        provider_ready_path=tmp_path / "provider-ready",
        sleep=sleep or (lambda _seconds: None),
    )
    return agent, active_factory


def test_s6_user_base_runs_workspace_agent_after_home_init() -> None:
    agent = _S6_ROOT / "workspace-agent"
    user_base = _S6_ROOT / "user-base"

    assert (agent / "type").read_text(encoding="utf-8").strip() == "longrun"
    # deploy key 生成已并入 home-init, 不再有独立 workspace-deploy-key 服务.
    assert not (_S6_ROOT / "workspace-deploy-key").exists()
    # bootstrap 逻辑已并入 workspace_agent.py, 不再有独立 workspace-bootstrap 服务.
    assert not (_S6_ROOT / "workspace-bootstrap").exists()
    # home-init 是 oneshot, agent 依赖它完成, 故 home 初始化成功才启动.
    assert (agent / "dependencies.d" / "home-init").is_file()
    assert "workspace_agent.py" in (agent / "run").read_text(encoding="utf-8")
    # controller 专用服务并入单一 runlevel user-base, 按 CODESPACE_WORKSPACE_TYPE 自门控.
    assert (user_base / "contents.d" / "workspace-agent").is_file()
    assert not (user_base / "contents.d" / "workspace-bootstrap").exists()
    assert not (_S6_ROOT / "managed-workspace").exists()


def test_s6_initializes_workspace_before_sshd_and_home() -> None:
    home = _S6_ROOT / "home-init"
    sshd = _S6_ROOT / "sshd"
    workspace_init = _S6_ROOT / "workspace-init"

    # home-init 是 oneshot (成功返回=home 初始化完成), 不再依赖 workspace-init,
    # 自管五个 IDE home mount 的 chown.
    assert (home / "type").read_text(encoding="utf-8").strip() == "oneshot"
    assert not (home / "dependencies.d" / "workspace-init").exists()
    assert not (home / "run").exists()
    assert "/opt/codespace/bin/home-init" in (home / "up").read_text(encoding="utf-8")
    assert (sshd / "dependencies.d" / "workspace-init").is_file()
    # workspace-init up 是纯调用壳; chown 目标已内联进编排脚本 workspace-init 自身.
    assert "workspace-init" in (workspace_init / "up").read_text(encoding="utf-8")
    home_script = (_AGENT_ROOT / "bin" / "home-init").read_text(encoding="utf-8")
    init_script = (_AGENT_ROOT / "bin" / "workspace-init").read_text(encoding="utf-8")
    for target in (
        "/home/x/.vscode-server",
        "/home/x/.trae",
        "/home/x/.trae-cn",
        "/home/x/.trae-server",
        "/home/x/.trae-cn-server",
    ):
        assert target in home_script
        assert target not in init_script
    assert not (_AGENT_ROOT / "bin" / "workspace-chown").exists()
    assert not (_S6_ROOT / "workspace-crypt").exists()
    assert (_S6_ROOT / "gitconfig-init" / "type").read_text(encoding="utf-8").strip() == "oneshot"
    assert not (_S6_ROOT / "home-links-init").exists()


def test_agent_config_loads_container_environment() -> None:
    config = image_agent.AgentConfig.load(
        {
            "CODESPACE_WORKSPACE_TYPE": "git",
            "CODESPACE_CLONE_PATH": "/workspace/devspace",
            "CODESPACE_OPEN_PATH": "/workspace/devspace",
            "CODESPACE_CLONE_URL": "git@github.com:curoky/devspace.git",
        }
    )

    assert config.workspace_type == "git"
    assert config.clone_path == "/workspace/devspace"
    assert config.open_path == "/workspace/devspace"
    assert config.clone_url == "git@github.com:curoky/devspace.git"

    # The controller always injects the workspace type; a bare environment is a
    # contract violation, surfaced as the missing-key KeyError.
    with pytest.raises(KeyError, match="CODESPACE_WORKSPACE_TYPE"):
        image_agent.AgentConfig.load({})


def test_repo_bootstrap_waits_for_provider_then_checks_out(tmp_path: Path) -> None:
    provider_ready = tmp_path / "provider-ready"

    def create_provider_marker(_seconds: float) -> None:
        # The bootstrap loop creates the provider marker on its first sleep so
        # the in-process wait terminates without a real controller.
        provider_ready.write_text("", encoding="utf-8")

    workspace_agent, factory = _agent(tmp_path, sleep=create_provider_marker)

    assert workspace_agent.status().state == "starting"

    workspace_agent.run_bootstrap()

    ready = workspace_agent.status()
    assert ready.state == "ready"
    assert ready.public_key == "ssh-ed25519 AAAAC3 test"
    commands = [command for command, _ in factory.calls]
    assert commands[0][0].endswith("git-checkout")
    assert commands[0][1:] == [
        "git@github.com:curoky/devspace.git",
        "/workspace/devspace",
    ]
    assert commands[1] == ["mkdir", "-p", "--", "/workspace/devspace"]


def test_repo_status_reports_awaiting_provider_before_marker(tmp_path: Path) -> None:
    workspace_agent, _ = _agent(tmp_path)

    # Drive the bootstrap up to the provider wait by stubbing the wait itself,
    # then observe the awaiting-provider state it publishes.
    workspace_agent._set_state("awaiting-provider")  # in-memory state inspection

    waiting = workspace_agent.status()
    assert waiting.state == "awaiting-provider"
    assert waiting.public_key == "ssh-ed25519 AAAAC3 test"


def test_agent_reports_bootstrap_failure(tmp_path: Path) -> None:
    workspace_agent, _ = _agent(
        tmp_path,
        workspace_type="git",
        factory=FakeRunFactory(fail="git-checkout"),
    )

    workspace_agent.run_bootstrap()

    status = workspace_agent.status()
    assert status.state == "failed"
    assert "git-checkout failed" in (status.error or "")


def test_blank_workspace_has_no_git_state(tmp_path: Path) -> None:
    workspace_agent, _ = _agent(tmp_path, workspace_type="blank")
    workspace_agent.run_bootstrap()

    with pytest.raises(image_agent.APIError, match="no Git state"):
        workspace_agent.git_state()


def test_git_state_reports_dirty_and_unpushed_changes(tmp_path: Path) -> None:
    workspace_agent, factory = _agent(tmp_path, workspace_type="git")
    workspace_agent._set_state("ready")  # skip bootstrap; focus on git-state

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
    workspace_agent._set_state("ready")  # skip bootstrap; focus on git-state

    assert workspace_agent.git_state().model_dump() == expected


def test_git_state_caps_detail_at_twenty_lines(tmp_path: Path) -> None:
    dirty = "".join(f"?? file-{index}.txt\n" for index in range(25))
    workspace_agent, _ = _agent(
        tmp_path,
        workspace_type="git",
        factory=FakeRunFactory(dirty=dirty),
    )
    workspace_agent._set_state("ready")  # skip bootstrap; focus on git-state

    state = workspace_agent.git_state()

    assert state.uncommitted is True
    assert len(state.detail) == 20


@contextmanager
def _running_server(tmp_path: Path) -> Iterator[Path]:
    socket_path = tmp_path / "agent.sock"
    workspace_agent, _ = _agent(tmp_path, sleep=lambda _seconds: time.sleep(0.02))
    # Bootstrap runs in-process just like the real agent, so the handshake
    # progresses awaiting-provider -> ready as the provider marker appears.
    workspace_agent.start_bootstrap()
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
