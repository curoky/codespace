"""Verify root password initialization without modifying system authentication."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

_HELPER = Path("platform/container/workspace/rootfs/opt/codespace/bin/init-root-password")


@pytest.fixture
def password_init(tmp_path: Path) -> Path:
    commands = {
        "setuidgid": """#!/bin/sh
set -eu
test "$1" = x
shift
exec "$@"
""",
        "env": """#!/bin/sh
set -eu
test "$1" = HOME=/home/x
exec /usr/bin/env "$@"
""",
        "csecret": """#!/bin/sh
set -eu
test "$HOME" = /home/x
test "$#" = 2
test "$1" = get
test "$2" = codespace_root_password
cat "$TEST_DIRECTORY/password"
exit "${TEST_CSECRET_STATUS:-0}"
""",
        "chpasswd": """#!/bin/sh
set -eu
test "$#" = 2
test "$1" = --crypt-method
test "$2" = SHA512
cat >"$TEST_DIRECTORY/chpasswd-input"
exit "${TEST_CHPASSWD_STATUS:-0}"
""",
    }
    for name, source in commands.items():
        path = tmp_path / name
        path.write_text(source)
        path.chmod(0o755)
    source = (
        _HELPER.read_text()
        .replace("/usr/local/bin/s6-setuidgid", str(tmp_path / "setuidgid"))
        .replace("/usr/local/bin/s6-env", str(tmp_path / "env"))
        .replace("/home/x/.local/bin/csecret", str(tmp_path / "csecret"))
        .replace("/usr/sbin/chpasswd", str(tmp_path / "chpasswd"))
    )
    helper = tmp_path / "init-root-password"
    helper.write_text(source)
    return helper


def run_init(helper: Path, **environment: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(helper)],  # noqa: S607
        env={
            **os.environ,
            "TEST_DIRECTORY": str(helper.parent),
            "CODESPACE_ROOT_PASSWORD_REQUIRED": "true",
            **environment,
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("password", ["fixture-password", " leading and trailing ", "a:b$'\\"])
def test_password_passes_privately_to_chpasswd(password_init: Path, password: str) -> None:
    (password_init.parent / "password").write_text(password)

    result = run_init(password_init)

    assert result.returncode == 0
    assert not result.stdout
    assert not result.stderr
    assert (password_init.parent / "chpasswd-input").read_text() == f"root:{password}\n"


@pytest.mark.parametrize("password", ["", "\n", "first\nsecond", "trailing\n", "carriage\r"])
def test_invalid_password_does_not_change_authentication(
    password_init: Path, password: str
) -> None:
    (password_init.parent / "password").write_text(password)

    result = run_init(password_init)

    assert result.returncode != 0
    assert not result.stdout
    assert result.stderr == "Workspace requires a non-empty, single-line root password in csecret\n"
    assert not (password_init.parent / "chpasswd-input").exists()


def test_failed_csecret_does_not_use_partial_output(password_init: Path) -> None:
    (password_init.parent / "password").write_text("partial-private-value")

    result = run_init(password_init, TEST_CSECRET_STATUS="42")

    assert result.returncode == 42
    assert not result.stdout
    assert not result.stderr
    assert not (password_init.parent / "chpasswd-input").exists()


def test_chpasswd_failure_is_not_hidden(password_init: Path) -> None:
    (password_init.parent / "password").write_text("fixture-password")

    result = run_init(password_init, TEST_CHPASSWD_STATUS="43")

    assert result.returncode == 43
    assert not result.stdout
    assert not result.stderr


def test_wsl_skips_csecret_and_authentication(password_init: Path) -> None:
    result = run_init(password_init, CODESPACE_ROOT_PASSWORD_REQUIRED="false")

    assert result.returncode == 0
    assert not result.stdout
    assert not result.stderr
    assert not (password_init.parent / "chpasswd-input").exists()
