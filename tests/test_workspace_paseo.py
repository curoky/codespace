"""Workspace-only Paseo installation and native Codex routing contracts."""

# ruff: noqa: S603

import json
import os
import subprocess
from pathlib import Path

import pytest

_WORKSPACE = Path(__file__).resolve().parents[1] / "platform/container/workspace"
_HOME = _WORKSPACE / "rootfs/home/x"
_SERVICE = _WORKSPACE / "rootfs/etc/s6/s6-rc.d/paseo"


def test_paseo_uses_native_llmbox_configuration_without_copying_credentials() -> None:
    config = json.loads((_HOME / ".paseo/config.json").read_text())
    provider = config["agents"]["providers"]["codex"]

    assert provider["env"] == {"CODEX_HOME": "/home/x/.codex-paseo"}
    assert "command" not in provider
    codex_home = _HOME / ".codex-paseo"
    assert {path.name for path in codex_home.iterdir()} == {"config.toml", "AGENTS.md", "skills"}
    for name, target in {
        "config.toml": "llmbox.config.toml",
        "AGENTS.md": "AGENTS.md",
        "skills": "skills",
    }.items():
        assert (codex_home / name).readlink() == Path("../.codex") / target


def test_paseo_daemon_starts_by_default_and_waits_for_llmbox() -> None:
    config = json.loads((_HOME / ".paseo/config.json").read_text())
    services = _SERVICE.parent

    assert config["version"] == 1
    assert config["daemon"]["listen"] == "0.0.0.0:8030"
    assert config["daemon"]["relay"]["enabled"] is False
    assert config["features"]["dictation"]["enabled"] is False
    assert config["features"]["voiceMode"]["enabled"] is False
    assert config["features"]["webUi"]["enabled"] is True
    assert (services / "default/contents.d/paseo").is_file()
    wsl_bundle = _WORKSPACE.parents[1] / "wsl/rootfs/etc/s6/s6-rc.d/wsl/contents.d"
    assert not (wsl_bundle / "paseo").exists()
    assert not (wsl_bundle / "default").exists()
    assert {path.name for path in (_SERVICE / "dependencies.d").iterdir()} == {
        "custom-job",
        "gocryptfs-workspace",
    }
    run = (_SERVICE / "run").read_text()
    assert (_SERVICE / "type").read_text().strip() == "longrun"
    assert os.access(_SERVICE / "run", os.X_OK)
    assert "s6-setuidgid x\ns6-env HOME=/home/x\ncd /workspace" in run
    assert "127.0.0.1:8030/api/health" in run
    assert run.index("s6-notifyoncheck") < run.index("s6-setuidgid")
    assert (_SERVICE / "notification-fd").read_text().strip() == "3"
    assert int((_SERVICE / "timeout-up").read_text()) > 60000


def test_paseo_installation_is_isolated_with_explicit_native_builds() -> None:
    dockerfile = (_WORKSPACE / "Dockerfile").read_text()

    assert "node-tool install @getpaseo/cli@0.17.6" in dockerfile
    for package in ("node-pty", "esbuild", "msgpackr-extract"):
        assert f"--allow-build {package}" in dockerfile


@pytest.fixture
def paseo_entrypoint(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    paseo = tmp_path / "paseo"
    paseo.write_text(
        '#!/usr/bin/env bash\nset -eu\ntest "$1 $2" = "daemon run"\n'
        'test "$PASEO_PASSWORD" = "$TEST_SECRET"\nprintf "%s\\n%s\\n" "$HOME" "$PATH"\n'
    )
    paseo.chmod(0o755)
    csecret = tmp_path / "csecret"
    csecret.write_text(
        '#!/usr/bin/env bash\nset -eu\ntest "$1 $2" = "get paseo_password"\n'
        'printf %s "$TEST_SECRET"\nexit "$TEST_SECRET_EXIT"\n'
    )
    csecret.chmod(0o755)
    node = tmp_path / "node"
    node.write_text(
        '#!/usr/bin/env bash\ntest "$1" = "-e" || exit 99\nexit "$TEST_VALIDATION_EXIT"\n'
    )
    node.chmod(0o755)
    profile = _WORKSPACE / "rootfs/etc/profile.d/app.sh"
    script = tmp_path / "run.sh"
    script.write_text(
        (_SERVICE / "run.sh")
        .read_text()
        .replace("/etc/profile.d/app.sh", str(profile))
        .replace("/home/x/.local/bin/csecret", str(csecret))
        .replace("/home/x/.local/opt/node/tools/bin/paseo", str(paseo))
    )
    return script, {
        "HOME": str(tmp_path),
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "TEST_SECRET": "fixture-password",
        "TEST_SECRET_EXIT": "0",
        "TEST_VALIDATION_EXIT": "0",
    }


def test_paseo_foreground_entrypoint_loads_profile_and_requires_password(
    paseo_entrypoint: tuple[Path, dict[str, str]],
) -> None:
    script, environment = paseo_entrypoint
    result = subprocess.run(
        ["/bin/bash", str(script)],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )

    home, path = result.stdout.splitlines()
    assert home == environment["HOME"]
    assert str(Path(home) / ".local/opt/node/nodejs26/bin") in path.split(":")
    assert "/nix/var/nix/profiles/default/bin" in path.split(":")
    assert environment["TEST_SECRET"] not in result.stdout + result.stderr
    assert "process.env.PASEO_PASSWORD?.trim()" in script.read_text()


@pytest.mark.parametrize(
    ("secret", "secret_exit", "validation_exit"),
    [("", "1", "0"), ("", "0", "1"), (" \t", "0", "1"), ("\ufeff", "0", "1")],
)
def test_paseo_does_not_start_without_a_valid_password(
    paseo_entrypoint: tuple[Path, dict[str, str]],
    secret: str,
    secret_exit: str,
    validation_exit: str,
) -> None:
    script, environment = paseo_entrypoint
    result = subprocess.run(
        ["/bin/bash", str(script)],
        env={
            **environment,
            "TEST_SECRET": secret,
            "TEST_SECRET_EXIT": secret_exit,
            "TEST_VALIDATION_EXIT": validation_exit,
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert not result.stdout
