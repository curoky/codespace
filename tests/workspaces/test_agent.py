"""Tests for the fixed HTTP-over-UDS Workspace agent client."""

# ruff: noqa: S603, S607

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from socketserver import BaseRequestHandler, UnixStreamServer

import httpx
import pytest
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


@contextmanager
def running_image_agent(
    binary: Path,
    home: Path,
    sources: list[dict[str, object]],
    *,
    checkout: Path | None = None,
    environment: dict[str, str] | None = None,
) -> Iterator[agent.WorkspaceAgentClient]:
    home.mkdir(parents=True, exist_ok=True)
    helper = checkout or (
        Path(__file__).resolve().parents[2]
        / "platform/container/workspace/rootfs/opt/codespace/bin/checkout"
    )
    with tempfile.TemporaryDirectory(prefix="agent-", dir="/tmp") as directory:
        socket = Path(directory) / "agent.sock"
        with subprocess.Popen(
            [str(binary), "--socket", str(socket), "--checkout", str(helper)],
            env={
                **os.environ,
                "HOME": str(home),
                "CODESPACE_SOURCES": json.dumps(sources),
                "CODESPACE_OPEN_PATH": str(home / "open path"),
                **(environment or {}),
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as process:
            try:
                yield agent.WorkspaceAgentClient(socket)
            finally:
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()
                    raise
                assert process.returncode == 0, stdout + stderr
                assert not socket.exists()


def test_image_empty_workspace_protocol(
    workspace_binaries: dict[str, Path], tmp_path: Path
) -> None:
    with running_image_agent(workspace_binaries["workspace-agent"], tmp_path, []) as client:
        assert client.wait_for("ready", timeout=5).model_dump() == {
            "state": "ready",
            "public_key": None,
            "error": None,
        }
        with pytest.raises(agent.AgentError, match="empty workspace"):
            client.git_state()
        with pytest.raises(agent.AgentError, match=r"failed \(409\)"):
            client.authorize_provider()


def test_image_checks_out_and_inspects_multiple_real_repositories(
    workspace_binaries: dict[str, Path], tmp_path: Path
) -> None:
    sources: list[dict[str, object]] = []
    for index in range(2):
        remote = tmp_path / f"remote-{index}"
        subprocess.run(["git", "init", "-q", str(remote)], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(remote),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "--allow-empty",
                "-qm",
                "initial",
            ],
            check=True,
        )
        sources.append(
            {
                "type": "git",
                "clone_url": str(remote),
                "checkout_path": str(tmp_path / f"checkout-{index}"),
                "args": [],
            }
        )
    with running_image_agent(workspace_binaries["workspace-agent"], tmp_path, sources) as client:
        client.wait_for("ready", timeout=5)
        assert client.git_state().model_dump() == {
            "unpushed": False,
            "uncommitted": False,
            "detail": [],
        }
        (tmp_path / "checkout-0/untracked.txt").write_text("local work\n")
        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_path / "checkout-1"),
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.com",
                "commit",
                "--allow-empty",
                "-qm",
                "unpublished",
            ],
            check=True,
        )
        state = client.git_state()
        assert state.uncommitted and state.unpushed
        assert any("checkout-0" in detail for detail in state.detail)
        assert any("checkout-1" in detail for detail in state.detail)


@pytest.mark.parametrize("provider", ["github", "gitlab"])
@pytest.mark.parametrize("checkout_fails", [False, True])
def test_image_provider_lifecycle_over_real_socket(
    workspace_binaries: dict[str, Path], tmp_path: Path, provider: str, checkout_fails: bool
) -> None:
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh/git_deploy_key_ed25519.pub").write_text("ssh-ed25519 PUBLIC\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text("#!/usr/bin/env bash\nprintf 'Permission denied (publickey)' >&2\nexit 128\n")
    git.chmod(0o755)
    checkout = tmp_path / "checkout"
    checkout.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" >checkout-args\n"
        + ("printf 'checkout failed' >&2\nexit 42\n" if checkout_fails else "")
    )
    checkout.chmod(0o755)
    sources: list[dict[str, object]] = [
        {
            "type": provider,
            "clone_url": "git@example.com:owner/repo.git",
            "checkout_path": "/workspace/repo",
            "args": ["--depth=1"],
        }
    ]
    with running_image_agent(
        workspace_binaries["workspace-agent"],
        tmp_path,
        sources,
        checkout=checkout,
        environment={"PATH": f"{bin_dir}:{os.environ['PATH']}"},
    ) as client:
        assert client.wait_for("awaiting-provider", timeout=5).public_key == "ssh-ed25519 PUBLIC"
        assert not (tmp_path / "checkout-args").exists()
        client.authorize_provider()
        if checkout_fails:
            with pytest.raises(agent.AgentError, match="checkout failed"):
                client.wait_for("ready", timeout=5)
            assert client.status().state == "failed"
            with pytest.raises(agent.AgentError, match=r"failed \(409\)"):
                client.authorize_provider()
        else:
            client.wait_for("ready", timeout=5)
            client.authorize_provider()
            client.authorize_provider()
        assert (tmp_path / "checkout-args").read_text().splitlines() == [
            "git@example.com:owner/repo.git",
            "/workspace/repo",
            "--depth=1",
        ]
