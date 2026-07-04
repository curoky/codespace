import socket
import threading
from contextlib import closing

import pytest

from codespace.agent import podman_ops


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_wait_for_ssh_ready_accepts_listening_port(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    ready = threading.Event()

    def _server() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(1)
            ready.set()
            conn, _ = sock.accept()
            conn.close()

    thread = threading.Thread(target=_server)
    thread.start()
    ready.wait(timeout=1)
    monkeypatch.setattr(podman_ops, "_READY_TIMEOUT_S", 0.2)
    monkeypatch.setattr(podman_ops, "_READY_INTERVAL_S", 0.01)

    podman_ops.wait_for_ssh_ready(port)

    thread.join(timeout=1)


def test_wait_for_ssh_ready_accepts_preauth_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    ready = threading.Event()

    def _server() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen(1)
            ready.set()
            conn, _ = sock.accept()
            with conn:
                conn.sendall(b"Not allowed at this time\r\n")

    thread = threading.Thread(target=_server)
    thread.start()
    ready.wait(timeout=1)
    monkeypatch.setattr(podman_ops, "_READY_TIMEOUT_S", 0.2)
    monkeypatch.setattr(podman_ops, "_READY_INTERVAL_S", 0.01)

    podman_ops.wait_for_ssh_ready(port)

    thread.join(timeout=1)


def test_wait_for_ssh_ready_rejects_closed_port(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    monkeypatch.setattr(podman_ops, "_READY_TIMEOUT_S", 0.05)
    monkeypatch.setattr(podman_ops, "_READY_INTERVAL_S", 0.01)

    with pytest.raises(RuntimeError, match="did not start listening"):
        podman_ops.wait_for_ssh_ready(port)
