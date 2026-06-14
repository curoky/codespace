"""Image entrypoints must preserve bridge reachability and loopback isolation."""

# ruff: noqa: S104, S603, S607

import os
import subprocess
from pathlib import Path

import pytest

_CONTAINER = Path(__file__).resolve().parents[1] / "platform/container"
_WORKSPACE_ROOT = _CONTAINER / "workspace/rootfs"
_WORKSPACE_AGENT = _CONTAINER / "workspace/agent/agent.py"
_WSL_BOOT = Path(__file__).resolve().parents[1] / "platform/wsl/rootfs/opt/codespace/wsl/boot.sh"


@pytest.mark.parametrize("service", ["vllm", "sglang"])
@pytest.mark.parametrize("bind", [None, "0.0.0.0"])
def test_inference_entrypoint_honors_bind_address(
    tmp_path: Path, service: str, bind: str | None
) -> None:
    venv = tmp_path / "venv"
    binary = venv / "bin" / ("vllm" if service == "vllm" else "python")
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    binary.chmod(0o755)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SERVE_")}
    environment.update(
        SERVE_VENV=str(venv), SERVE_PORT="18003", SERVE_EXTRA_ARGS="--max-model-len 8192"
    )
    if bind is not None:
        environment["SERVE_HOST"] = bind

    result = subprocess.run(
        ["bash", str(_CONTAINER / f"services/{service}/rootfs/opt/codespace/{service}/serve.sh")],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    args = result.stdout.splitlines()
    assert args[args.index("--host") + 1] == (bind or "127.0.0.1")
    assert args[args.index("--port") + 1] == "18003"
    if service == "vllm":
        assert args[-2:] == ["--max-model-len", "8192"]


@pytest.mark.parametrize(
    ("service", "listen"),
    [("rclone-webdav", "--addr 127.0.0.1:8004"), ("copyparty-webdav", "-i 127.0.0.1")],
)
def test_workspace_webdav_uses_fixed_loopback_listener(service: str, listen: str) -> None:
    script = (_WORKSPACE_ROOT / f"etc/s6/s6-rc.d/{service}/run").read_text()

    assert listen in script
    assert "SERVE_HOST" not in script
    assert "SSHD_BIND" not in script


def test_workspace_sshd_uses_fixed_listener() -> None:
    script = (_WORKSPACE_ROOT / "etc/s6/s6-rc.d/sshd/run").read_text()
    config = (_WORKSPACE_ROOT / "etc/ssh/sshd_config").read_text()

    assert "SSHD_PORT" not in script
    assert "SSHD_BIND" not in script
    assert "redirfd -w 1 /var/log/s6.sshd.log" in script
    assert "s6.sshd.stdout.log" not in script
    assert "sshd -D -e" in script
    assert "\n  -E " not in script
    assert "\nPort 22\n" in config
    assert "\nListenAddress 0.0.0.0\n" in config


def test_workspace_agent_requires_managed_bootstrap_environment() -> None:
    source = _WORKSPACE_AGENT.read_text()

    for name in ("CODESPACE_SOURCE_TYPE", "CODESPACE_CHECKOUT_PATH", "CODESPACE_OPEN_PATH"):
        assert f'os.environ["{name}"]' in source
    assert 'os.environ.get("CODESPACE_SOURCE_TYPE")' not in source
    assert "signal.pause" not in source


def test_wsl_declares_inherited_workspace_runtime_input() -> None:
    script = _WSL_BOOT.read_text()

    assert "container_environment/CODESPACE_ENCRYPTED" in script
    assert "SSHD_PORT" not in script
    assert "SSHD_BIND" not in script
