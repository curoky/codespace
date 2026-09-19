"""Tests for the fixed HTTP-over-UDS Workspace agent client."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from socketserver import BaseRequestHandler, UnixStreamServer
from types import ModuleType

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from codespace.workspaces import agent


@pytest.fixture
def responses() -> list[httpx.Response]:
    return []


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, responses: list[httpx.Response]
) -> agent.WorkspaceAgentClient:
    monkeypatch.setattr(
        httpx,
        "HTTPTransport",
        lambda **_kwargs: httpx.MockTransport(lambda _request: responses[-1]),
    )
    return agent.WorkspaceAgentClient(tmp_path / "agent.sock")


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
    responses: list[httpx.Response],
    payload: dict[str, object],
) -> None:
    responses.append(httpx.Response(200, json=payload))

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
    responses: list[httpx.Response],
    payload: dict[str, object],
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(agent.time, "sleep", sleeps.append)
    responses.append(httpx.Response(200, json=payload))

    with pytest.raises(agent.AgentError, match="invalid status") as caught:
        client.wait_for("ready", timeout=1)

    assert isinstance(caught.value.__cause__, ValidationError)
    assert sleeps == []


def test_failed_agent_state_stops_waiting(
    client: agent.WorkspaceAgentClient,
    responses: list[httpx.Response],
) -> None:
    payload = {"state": "failed", "public_key": None, "error": "checkout failed"}
    responses.append(httpx.Response(200, json=payload))

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
    responses: list[httpx.Response],
    payload: dict[str, object],
) -> None:
    responses.append(httpx.Response(200, json=payload))

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
    responses: list[httpx.Response],
    payload: dict[str, object],
) -> None:
    responses.append(httpx.Response(200, json=payload))

    assert client.git_state().model_dump() == payload


def test_http_error_reports_agent_detail(
    client: agent.WorkspaceAgentClient, responses: list[httpx.Response]
) -> None:
    responses.append(httpx.Response(409, json={"detail": "agent state is starting"}))

    with pytest.raises(agent.AgentError, match=r"failed \(409\): agent state is starting"):
        client.git_state()


@pytest.mark.parametrize("payload", [True, {}, {"authorized": True}, "null"])
def test_provider_authorization_rejects_invalid_response(
    client: agent.WorkspaceAgentClient, responses: list[httpx.Response], payload: object
) -> None:
    responses.append(httpx.Response(200, json=payload))

    with pytest.raises(agent.AgentError, match="invalid authorization response"):
        client.authorize_provider()


@pytest.mark.parametrize("payload", [{}, {"error": "wrong schema"}, {"detail": ""}])
def test_malformed_http_error_is_rejected(
    client: agent.WorkspaceAgentClient,
    responses: list[httpx.Response],
    payload: dict[str, object],
) -> None:
    responses.append(httpx.Response(409, json=payload))

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


@pytest.mark.parametrize("content", [b"not-json", b"\xff"])
def test_invalid_json_fails_without_retry(
    client: agent.WorkspaceAgentClient,
    responses: list[httpx.Response],
    monkeypatch: pytest.MonkeyPatch,
    content: bytes,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(agent.time, "sleep", sleeps.append)
    response = httpx.Response(200, content=content)
    responses.append(response)

    with pytest.raises(agent.AgentError, match="invalid JSON"):
        client.wait_for("ready", timeout=1)

    assert sleeps == []
    assert response.is_closed


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("oversized", agent.AgentError),
        ("read", agent.AgentUnavailable),
        ("interrupt", KeyboardInterrupt),
    ],
)
def test_stream_is_bounded_and_closed_on_failure(
    client: agent.WorkspaceAgentClient,
    responses: list[httpx.Response],
    failure: str,
    expected: type[BaseException],
) -> None:
    consumed: list[int] = []
    closed: list[bool] = []

    class Stream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            for _ in range(20):
                consumed.append(8192)
                yield b"x" * 8192
                if failure == "read":
                    raise httpx.ReadTimeout("response stalled")
                if failure == "interrupt":
                    raise KeyboardInterrupt

        def close(self) -> None:
            closed.append(True)

    response = httpx.Response(200, stream=Stream())
    responses.append(response)
    with pytest.raises(expected) as caught:
        client.status()

    assert sum(consumed) <= 64 * 1024 + 8192
    assert closed == [True]
    assert response.is_closed
    if failure == "oversized":
        assert str(caught.value) == "workspace agent response exceeds 64 KiB"
        assert not isinstance(caught.value, agent.AgentUnavailable)
    elif failure == "read":
        assert isinstance(caught.value.__cause__, httpx.ReadTimeout)


def test_missing_socket_is_unavailable(tmp_path: Path) -> None:
    with pytest.raises(agent.AgentUnavailable) as caught:
        agent.WorkspaceAgentClient(tmp_path / "missing.sock").status()
    assert isinstance(caught.value.__cause__, httpx.ConnectError)


def test_http_client_uses_real_unix_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[str] = []
    payloads = {
        "/status": {"state": "ready", "public_key": None, "error": None},
        "/git-state": {"unpushed": False, "uncommitted": True, "detail": [" M file"]},
        "/provider-ready": None,
    }

    class Handler(BaseRequestHandler):
        def handle(self) -> None:
            self.request.settimeout(2)
            with self.request.makefile("rb") as stream:
                request = stream.readline().decode()
                requests.append(request)
                while stream.readline().strip():
                    pass
            content = json.dumps(payloads[request.split()[1]]).encode()
            self.request.sendall(
                f"HTTP/1.1 200 OK\r\nContent-Length: {len(content)}\r\n\r\n".encode() + content
            )

    # UDS paths are limited to 103 bytes on the supported macOS client.
    with tempfile.TemporaryDirectory(prefix="cs-agent-", dir="/tmp") as directory:
        path = Path(directory) / "agent.sock"
        with UnixStreamServer(str(path), Handler) as server, ThreadPoolExecutor() as executor:
            server.timeout = 2
            monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
            client = agent.WorkspaceAgentClient(path)
            for target, read in (("/status", client.status), ("/git-state", client.git_state)):
                handled = executor.submit(server.handle_request)
                assert read().model_dump() == payloads[target]
                handled.result(timeout=3)
            handled = executor.submit(server.handle_request)
            assert client.authorize_provider() is None
            handled.result(timeout=3)

    assert requests == [
        "GET /status HTTP/1.1\r\n",
        "GET /git-state HTTP/1.1\r\n",
        "POST /provider-ready HTTP/1.1\r\n",
    ]


@pytest.fixture
def image_agent(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "platform/container/workspace/agent/agent.py"
    spec = importlib.util.spec_from_file_location("workspace_image_agent", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("git_args", "expected_checkout"),
    [
        (
            [],
            ["/opt/codespace/bin/checkout", "git@example.com:owner/repo.git", "/workspace/repo"],
        ),
        (
            ["--depth=1", "--single-branch"],
            [
                "/opt/codespace/bin/checkout",
                "git@example.com:owner/repo.git",
                "/workspace/repo",
                "--depth=1",
                "--single-branch",
            ],
        ),
    ],
)
def test_image_bootstrap_passes_git_args(
    image_agent: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    git_args: list[str],
    expected_checkout: list[str],
) -> None:
    commands: list[list[str]] = []
    worker = image_agent.WorkspaceAgent(
        "git",
        "/workspace/repo",
        "/workspace/repo",
        clone_url="git@example.com:owner/repo.git",
        git_args=git_args,
    )
    monkeypatch.setattr(
        image_agent,
        "run_command",
        lambda command, **_kwargs: (
            commands.append(command),
            subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
        )[-1],
    )

    worker.run_bootstrap()

    assert commands[0] == expected_checkout
    assert worker.status().state == "ready"


@pytest.mark.parametrize("source", ["empty", "git"])
@pytest.mark.parametrize("fail", [False, True])
def test_image_bootstrap_responses_satisfy_client_contract(
    image_agent: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: str,
    fail: bool,
) -> None:
    key = tmp_path / "key.pub"
    key.write_text("ssh-ed25519 PUBLIC\n")
    worker = image_agent.WorkspaceAgent(
        source,
        "/workspace/repo",
        "/workspace/repo",
        clone_url=None if source == "empty" else "git@example.com:owner/repo.git",
        deploy_public_key_path=key,
    )
    with TestClient(image_agent.create_app(worker)) as server:

        def request(request: httpx.Request) -> httpx.Response:
            response = server.request(request.method, request.url.path)
            return httpx.Response(response.status_code, content=response.content)

        monkeypatch.setattr(
            httpx,
            "HTTPTransport",
            lambda **_kwargs: httpx.MockTransport(request),
        )
        client = agent.WorkspaceAgentClient(tmp_path / "agent.sock")

        def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if fail:
                raise RuntimeError("checkout failed")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        monkeypatch.setattr(image_agent, "run_command", run)
        with pytest.raises(agent.AgentError, match=r"failed \(409\)"):
            client.authorize_provider()
        worker.run_bootstrap()
        assert client.status().state == ("failed" if fail else "ready")
        with pytest.raises(agent.AgentError, match=r"failed \(409\)"):
            client.authorize_provider()


@pytest.mark.parametrize("source", ["github", "gitlab"])
@pytest.mark.parametrize("checkout_fails", [False, True])
def test_image_provider_bootstrap_waits_for_publickey_authorization(
    image_agent: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: str,
    checkout_fails: bool,
) -> None:
    key = tmp_path / "key.pub"
    key.write_text("ssh-ed25519 PUBLIC\n")
    worker = image_agent.WorkspaceAgent(
        source,
        "/workspace/repo",
        "/workspace/repo",
        clone_url="git@example.com:owner/repo.git",
        deploy_public_key_path=key,
    )
    commands: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if command[:2] == ["git", "ls-remote"]:
            assert kwargs == {"check": False}
            return subprocess.CompletedProcess(
                command,
                128,
                stdout="",
                stderr="git@example.com: Permission denied (publickey).\n",
            )
        if checkout_fails and command[0] == image_agent.CHECKOUT:
            raise RuntimeError("checkout failed")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(image_agent, "run_command", run)
    with TestClient(image_agent.create_app(worker)) as server:

        def request(request: httpx.Request) -> httpx.Response:
            response = server.request(request.method, request.url.path)
            return httpx.Response(response.status_code, content=response.content)

        monkeypatch.setattr(
            httpx,
            "HTTPTransport",
            lambda **_kwargs: httpx.MockTransport(request),
        )
        client = agent.WorkspaceAgentClient(tmp_path / "agent.sock")
        thread = worker.start_bootstrap()
        try:
            status = client.wait_for("awaiting-provider", timeout=2)
            assert status.public_key == "ssh-ed25519 PUBLIC"
            assert commands == [["git", "ls-remote", "git@example.com:owner/repo.git"]]
            client.authorize_provider()
            thread.join(timeout=2)
            assert not thread.is_alive()
        finally:
            worker._provider_authorized.set()
            thread.join(timeout=2)

        assert client.status().state == ("failed" if checkout_fails else "ready")
        if checkout_fails:
            with pytest.raises(agent.AgentError, match=r"failed \(409\)"):
                client.authorize_provider()
        else:
            client.authorize_provider()
            client.authorize_provider()


def test_image_provider_probe_reports_network_failure(
    image_agent: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    key = tmp_path / "key.pub"
    key.write_text("ssh-ed25519 PUBLIC\n")
    worker = image_agent.WorkspaceAgent(
        "github",
        "/workspace/repo",
        "/workspace/repo",
        clone_url="git@example.com:owner/repo.git",
        deploy_public_key_path=key,
    )
    monkeypatch.setattr(
        image_agent,
        "run_command",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            128,
            stdout="",
            stderr="ssh: Could not resolve hostname example.com: Name or service not known\n",
        ),
    )

    worker.run_bootstrap()

    assert worker.status().state == "failed"
    assert "Could not resolve hostname" in worker.status().error


@pytest.mark.parametrize("source", ["github", "gitlab"])
def test_image_provider_restart_rechecks_remote_without_local_state(
    image_agent: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    source: str,
) -> None:
    key = tmp_path / "key.pub"
    key.write_text("ssh-ed25519 PUBLIC\n")
    commands: list[list[str]] = []
    monkeypatch.setattr(
        image_agent,
        "run_command",
        lambda command, **_kwargs: (
            commands.append(command),
            subprocess.CompletedProcess(command, 0, stdout="", stderr=""),
        )[-1],
    )
    worker = image_agent.WorkspaceAgent(
        source,
        "/workspace/repo",
        "/workspace/repo",
        clone_url="git@example.com:owner/repo.git",
        deploy_public_key_path=key,
    )

    worker.run_bootstrap()

    assert worker.status().state == "ready"
    assert commands == [
        ["git", "ls-remote", "git@example.com:owner/repo.git"],
        [image_agent.CHECKOUT, "git@example.com:owner/repo.git", "/workspace/repo"],
        ["mkdir", "-p", "--", "/workspace/repo"],
    ]


def test_image_git_and_error_responses_satisfy_client_contract(
    image_agent: ModuleType,
    client: agent.WorkspaceAgentClient,
    responses: list[httpx.Response],
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
        responses.append(httpx.Response(response.status_code, content=response.content))
        with pytest.raises(agent.AgentError, match="agent state is 'starting'"):
            client.git_state()

        worker.run_bootstrap()
        response = server.get("/git-state")
        assert response.status_code == 200
        responses.append(httpx.Response(response.status_code, content=response.content))
        assert client.git_state().model_dump() == {
            "unpushed": False,
            "uncommitted": False,
            "detail": [],
        }


@pytest.mark.parametrize(
    "state", ["missing", "not-repository", "empty", "orphan", "detached", "dirty"]
)
def test_image_git_state_reads_actual_repository_state(
    image_agent: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    state: str,
) -> None:
    checkout = tmp_path / "checkout"

    def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, check=check, capture_output=True, text=True)  # noqa: S603

    if state != "missing":
        checkout.mkdir()
    if state not in {"missing", "not-repository"}:
        run(["git", "init", "-q", str(checkout)])
    if state in {"orphan", "detached"}:
        run(
            [
                "git",
                "-C",
                str(checkout),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "--allow-empty",
                "-qm",
                "unpublished commit",
            ]
        )
        if state == "orphan":
            run(["git", "-C", str(checkout), "checkout", "--orphan", "new-branch"])
        else:
            run(["git", "-C", str(checkout), "checkout", "--detach"])
            for ref in run(
                ["git", "-C", str(checkout), "for-each-ref", "--format=%(refname)", "refs/heads"]
            ).stdout.splitlines():
                run(["git", "-C", str(checkout), "update-ref", "-d", ref])
    if state == "dirty":
        (checkout / "untracked.txt").write_text("local work\n")

    worker = image_agent.WorkspaceAgent("git", str(checkout), str(checkout))
    worker._set_state("ready")
    monkeypatch.setattr(image_agent, "run_command", run)
    with TestClient(image_agent.create_app(worker), raise_server_exceptions=False) as server:
        response = server.get("/git-state")

    if state in {"missing", "not-repository"}:
        assert response.status_code == 500
    else:
        assert response.status_code == 200
        result = response.json()
        assert result["unpushed"] is (state in {"orphan", "detached"})
        assert result["uncommitted"] is (state == "dirty")
        if state in {"orphan", "detached"}:
            assert result["detail"][0].endswith(" unpublished commit")
