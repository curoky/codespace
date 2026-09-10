"""Image entrypoints must preserve bridge reachability and loopback isolation."""

# ruff: noqa: S104, S603, S607

import os
import subprocess
from pathlib import Path

import pytest

_CONTAINER = Path(__file__).resolve().parents[1] / "platform/container"
_WORKSPACE_ROOT = _CONTAINER / "workspace/rootfs"


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
    [("rclone-webdav", "--addr ${SERVE_HOST}:8004"), ("copyparty-webdav", "-i ${SERVE_HOST}")],
)
def test_webdav_uses_configured_host_with_loopback_default(service: str, listen: str) -> None:
    script = (_WORKSPACE_ROOT / f"etc/s6/s6-rc.d/{service}/run").read_text()

    import_host = "importas -D 127.0.0.1 SERVE_HOST SERVE_HOST"
    assert import_host in script
    assert script.index("s6-envdir -Lf -- /run/s6/container_environment") < script.index(
        import_host
    )
    assert listen in script
    assert script.index(import_host) < script.index(listen)
    assert "SSHD_BIND" not in script
