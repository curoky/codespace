"""Support image maintenance contract."""

# ruff: noqa: S603

import os
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SUPPORT = _ROOT / "platform/container/services/support"


def test_support_periodically_pulls_workspace_resource_image(tmp_path: Path) -> None:
    script = _SUPPORT / "rootfs/opt/support/pull-images.sh"
    crontab = (_SUPPORT / "rootfs/etc/supercronic/crontab").read_text().splitlines()

    assert "*/10 * * * * /opt/support/pull-images.sh" in crontab
    assert script.stat().st_mode & 0o111

    calls = tmp_path / "curl-calls"
    curl = tmp_path / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$*" >>"$CURL_CALLS"\n'
        'printf \'{"images":["sha256:test"]}\\n\'\n'
    )
    curl.chmod(0o755)

    subprocess.run(
        [script],
        check=True,
        env={
            **os.environ,
            "CURL_CALLS": str(calls),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
        },
    )

    requests = calls.read_text().splitlines()
    assert all("--unix-socket /run/podman/podman.sock" in request for request in requests)
    assert any(
        "reference=ghcr.io/curoky/codespace:workspace-resource" in request for request in requests
    )
