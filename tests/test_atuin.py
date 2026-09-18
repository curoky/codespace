"""Atuin belongs to the Workspace and gates client startup on server readiness."""

import os
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_WORKSPACE = _ROOT / "platform/container/workspace"
_S6 = _ROOT / "platform/container/services/s6"
_SUPPORT = _ROOT / "platform/container/services/support"
_SERVICES = _WORKSPACE / "rootfs/etc/s6/s6-rc.d"


def test_workspace_atuin_server_uses_private_secret_and_loopback() -> None:
    run = (_SERVICES / "atuin-server/run").read_text()
    secret = "backtick -i ATUIN_DB_URI { cat /run/secrets/atuin_db_uri }"
    assert "if { test -s /run/secrets/atuin_db_uri }" in run
    assert run.index(secret) < run.index("exec /opt/bm/store/atuin/bin/atuin server start")
    assert 'export ATUIN_HOST "127.0.0.1"' in run
    assert 'export ATUIN_PORT "8002"' in run
    assert 'export ATUIN_OPEN_REGISTRATION "false"' in run
    assert "importas" not in run
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
    assert "http://127.0.0.1:8002/" in run
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
    # supercronic (binary, service definition and `default` membership) lives in
    # the shared s6 base; support only supplies the maintenance crontab + scripts.
    assert (_S6 / "rootfs/etc/s6/s6-rc.d/default/contents.d/supercronic").is_file()
    assert (_S6 / "rootfs/etc/s6/s6-rc.d/supercronic/type").read_text().strip() == "longrun"
    assert "    - supercronic\n" in (_S6 / "binman.yaml").read_text()

    rootfs = _SUPPORT / "rootfs"
    payload = {path.relative_to(rootfs).as_posix() for path in rootfs.rglob("*") if path.is_file()}
    assert payload == {
        "etc/supercronic/crontab",
        "opt/support/pull-images.sh",
        "opt/support/prune-images.sh",
    }
    crontab = (rootfs / "etc/supercronic/crontab").read_text()
    assert "/opt/support/pull-images.sh" in crontab
    assert "/opt/support/prune-images.sh" in crontab
