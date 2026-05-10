"""Tests for remote Host data and command primitives."""

from __future__ import annotations

import subprocess

import pytest

from codespace.runtime import host
from codespace.runtime.transport import SSHRoute


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    host.remote_data_paths.cache_clear()


def test_remote_data_paths_uses_final_layout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        host.transport,
        "run_host",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            0,
            stdout="/home/x/codespace",
            stderr="",
        ),
    )

    paths = host.remote_data_paths(SSHRoute(host="home"))

    assert paths.workspace("codespace", "debug").root == (
        "/home/x/codespace/workspaces/codespace/debug"
    )
    assert paths.service("support") == "/home/x/codespace/services/support"


def test_prepare_directories_rejects_relative_path() -> None:
    with pytest.raises(RuntimeError, match="non-absolute"):
        host.prepare_directories(SSHRoute(host="home"), ["relative"])


def test_read_environment_requires_every_forwarded_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        host.transport,
        "run_host",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            [],
            0,
            stdout="HTTP_PROXY=http://proxy\0",
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="NO_PROXY"):
        host.read_environment(SSHRoute(host="home"), ["HTTP_PROXY", "NO_PROXY"])
