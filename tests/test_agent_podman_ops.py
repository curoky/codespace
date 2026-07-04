import socket
import threading
from contextlib import closing

import pytest

from codespace.agent import podman_ops


def _free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_wait_for_ssh_ready_accepts_ssh_banner(monkeypatch: pytest.MonkeyPatch) -> None:
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
                conn.sendall(b"SSH-2.0-test\r\n")

    thread = threading.Thread(target=_server)
    thread.start()
    ready.wait(timeout=1)
    monkeypatch.setattr(podman_ops, "_READY_TIMEOUT_S", 0.2)
    monkeypatch.setattr(podman_ops, "_READY_INTERVAL_S", 0.01)

    podman_ops.wait_for_ssh_ready(port)

    thread.join(timeout=1)


def test_wait_for_ssh_ready_rejects_empty_banner(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    stop = threading.Event()
    ready = threading.Event()

    def _server() -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            sock.listen()
            sock.settimeout(0.02)
            ready.set()
            while not stop.is_set():
                try:
                    conn, _ = sock.accept()
                except TimeoutError:
                    continue
                conn.close()

    thread = threading.Thread(target=_server, daemon=True)
    thread.start()
    ready.wait(timeout=1)
    monkeypatch.setattr(podman_ops, "_READY_TIMEOUT_S", 0.05)
    monkeypatch.setattr(podman_ops, "_READY_INTERVAL_S", 0.01)

    with pytest.raises(RuntimeError, match="did not become ready"):
        podman_ops.wait_for_ssh_ready(port)

    stop.set()
    thread.join(timeout=1)
