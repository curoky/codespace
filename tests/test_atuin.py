"""Atuin belongs to the Workspace and gates client startup on server readiness."""

import os
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKSPACE = _ROOT / "platform/container/workspace"
_SUPPORT = _ROOT / "platform/container/services/support"
_SERVICES = _WORKSPACE / "rootfs/etc/s6/s6-rc.d"


def test_workspace_atuin_server_uses_private_secret_and_loopback() -> None:
    run = (_SERVICES / "atuin-server/run").read_text()
    secret = "backtick -i ATUIN_DB_URI { cat /run/secrets/atuin_db_uri }"
    assert "if { test -s /run/secrets/atuin_db_uri }" in run
    assert run.index(secret) < run.index("exec /opt/bm/store/atuin/bin/atuin server start")
    assert 'importas -D "127.0.0.1" ATUIN_HOST ATUIN_HOST' in run
    assert 'importas -D "8002" ATUIN_PORT ATUIN_PORT' in run
    assert 'export ATUIN_OPEN_REGISTRATION "false"' in run
    assert os.access(_SERVICES / "atuin-server/run", os.X_OK)
    config = tomllib.loads((_WORKSPACE / "rootfs/home/x/.config/atuin/config.toml").read_text())
    assert config["sync_address"] == "http://127.0.0.1:8002"


def test_atuin_clients_depend_on_server_readiness() -> None:
    assert (_SERVICES / "atuin-server/type").read_text().strip() == "longrun"
    assert (_SERVICES / "atuin-server/notification-fd").read_text().strip() == "3"
    assert (_SERVICES / "atuin-server/timeout-up").read_text().strip() == "65000"
    run = (_SERVICES / "atuin-server/run").read_text()
    assert "s6-notifyoncheck" in run
    assert "--fail" in run
    assert "http://${ATUIN_HOST}:${ATUIN_PORT}/" in run
    assert (_SERVICES / "default/contents.d/atuin-server").is_file()
    assert (_SERVICES / "atuin-login/dependencies.d/atuin-server").is_file()
    assert (_SERVICES / "atuin-daemon/dependencies.d/atuin-login").is_file()
    for service in ("sshd", "workspace-agent"):
        assert not (_SERVICES / f"{service}/dependencies.d/atuin-server").exists()
    login = (_SERVICES / "atuin-login/up").read_text()
    assert "if { /opt/bm/store/atuin/bin/atuin login" in login
    wsl = _ROOT / "platform/wsl/rootfs/etc/s6/s6-rc.d/wsl/contents.d"
    assert (wsl / "atuin-login").is_file()


def test_support_contains_only_image_maintenance() -> None:
    bundle = _SUPPORT / "rootfs/etc/s6/s6-rc.d/default/contents.d"
    assert {path.name for path in bundle.iterdir()} == {"supercronic"}
    manifest = yaml.safe_load((_SUPPORT / "binman.yaml").read_text())
    assert manifest["packages"]["link"] == ["supercronic"]


@pytest.mark.parametrize("platform", ["linux", "macos"])
def test_support_smoke_needs_no_secret_or_published_port(tmp_path: Path, platform: str) -> None:
    podman = tmp_path / "podman"
    events = tmp_path / "events"
    podman.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" >> "$EVENTS"\nif [ "$1" = container ]; then exit 1; fi\n'
    )
    podman.chmod(0o755)
    subprocess.run(  # noqa: S603
        ["/bin/bash", str(_SUPPORT / f"smoke-{platform}.sh")],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "EVENTS": str(events)},
        check=True,
        capture_output=True,
    )
    args = events.read_text().splitlines()
    assert "run" in args
    assert "--network" in args
    assert "--publish" not in args
    assert "--secret" not in args
    assert "secret" not in args
    assert not any("ATUIN" in arg for arg in args)
