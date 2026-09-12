"""Image entrypoints must preserve bridge reachability and loopback isolation."""

# ruff: noqa: S104, S603, S607

import configparser
import mimetypes
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
    [
        ("rclone-webdav", "--addr 127.0.0.1:8004"),
        ("copyparty-webdav", "-i 127.0.0.1"),
        ("rclone-http", "--addr 127.0.0.1:8007"),
        ("miniserve-http", "--interfaces 127.0.0.1"),
    ],
)
def test_workspace_file_services_use_fixed_loopback_listener(service: str, listen: str) -> None:
    script = (_WORKSPACE_ROOT / f"etc/s6/s6-rc.d/{service}/run").read_text()

    assert listen in script
    assert "SERVE_HOST" not in script
    assert "SSHD_BIND" not in script


def test_workspace_rclone_services_share_combined_remote() -> None:
    config = configparser.ConfigParser()
    config.read(_WORKSPACE_ROOT / "etc/rclone.conf")

    assert config["files"]["type"] == "combine"
    assert config["files"]["upstreams"].split() == [
        "workspace=workspace:",
        "logs=logs:",
        "upload=/upload",
    ]
    assert config["logs"]["upstreams"].split() == ["/var/log:ro", "empty::ro"]
    for service, protocol in (("rclone-webdav", "webdav"), ("rclone-http", "http")):
        script = (_WORKSPACE_ROOT / f"etc/s6/s6-rc.d/{service}/run").read_text()
        assert f"rclone serve {protocol} files:" in script
        assert "--config /etc/rclone.conf" in script
        assert (_WORKSPACE_ROOT / f"etc/s6/s6-rc.d/default/contents.d/{service}").exists()
        assert (
            _WORKSPACE_ROOT / f"etc/s6/s6-rc.d/{service}/dependencies.d/workspace-init"
        ).exists()

    http_script = (_WORKSPACE_ROOT / "etc/s6/s6-rc.d/rclone-http/run").read_text()
    assert "--disable-dir-list" not in http_script
    assert '--response-header "Content-Disposition: inline"' in http_script

    mime_types = mimetypes.read_mime_types(_WORKSPACE_ROOT / "etc/mime.types")
    assert mime_types is not None
    for extension in (".log", ".toml", ".yaml", ".py", ".go"):
        assert mime_types[extension].startswith("text/")


def test_workspace_copyparty_exposes_container_logs_read_only() -> None:
    script = (_WORKSPACE_ROOT / "etc/s6/s6-rc.d/copyparty-webdav/run").read_text()

    assert "-v /var/log:logs:r\n" in script


def test_workspace_miniserve_exposes_container_logs_read_only() -> None:
    service = _WORKSPACE_ROOT / "etc/s6/s6-rc.d/miniserve-http"
    script = (service / "run").read_text()

    assert "exec /opt/bm/bin/miniserve" in script
    assert "--port 8008" in script
    assert "--no-symlinks" in script
    assert script.rstrip().endswith("/var/log")
    for setting in (
        "MINISERVE_ENABLE_TAR",
        "MINISERVE_ENABLE_TAR_GZ",
        "MINISERVE_ENABLE_ZIP",
        "MINISERVE_SHOW_SYMLINK_INFO",
        "MINISERVE_SHOW_WGET_FOOTER",
    ):
        assert f"s6-env {setting}=false" in script
    assert all(option not in script for option in ("--upload-files", "--mkdir", "--rm-files"))
    assert (_WORKSPACE_ROOT / "etc/s6/s6-rc.d/default/contents.d/miniserve-http").exists()


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
