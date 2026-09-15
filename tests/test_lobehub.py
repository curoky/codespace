"""LobeHub packages its application and database as one persistent Service."""

import os
import subprocess
from pathlib import Path

import yaml

from codespace.config import Config

_ROOT = Path(__file__).resolve().parents[1]
_SERVICE = _ROOT / "platform/container/services/lobehub"
_S6 = _SERVICE / "rootfs/etc/s6/s6-rc.d"


def test_lobehub_image_pins_upstream_and_initializes_database_at_runtime() -> None:
    dockerfile = (_SERVICE / "Dockerfile").read_text()
    database = (_SERVICE / "rootfs/opt/codespace/lobehub/database.sh").read_text()

    assert "lobehub/lobehub:2.2.17" in dockerfile
    assert "paradedb/paradedb:0.25.9-pg17" in dockerfile
    assert "node:24.21.0-bookworm-slim" in dockerfile
    assert "initdb" in database
    assert "shared_preload_libraries=pg_search" in database
    assert not (_SERVICE / "rootfs/var/lib/postgresql").exists()


def test_lobehub_waits_for_local_postgres_and_persists_runtime_identity() -> None:
    assert (_S6 / "postgres/type").read_text().strip() == "longrun"
    assert (_S6 / "postgres/notification-fd").read_text().strip() == "3"
    assert (_S6 / "lobehub/type").read_text().strip() == "longrun"
    assert (_S6 / "lobehub/dependencies.d/postgres").is_file()
    assert (_S6 / "default/contents.d/lobehub").is_file()

    serve = (_SERVICE / "rootfs/opt/codespace/lobehub/serve.sh").read_text()
    assert 'data_root="${LOBEHUB_DATA_DIR:-/var/lib/codespace/lobehub}"' in serve
    assert 'config_dir="${data_root}/config"' in serve
    assert "postgresql://postgres@127.0.0.1:5432/lobehub" in serve
    assert "s6-setuidgid nextjs" in serve


def test_lobehub_example_is_loopback_only_and_targets_sglang() -> None:
    config = Config.model_validate(yaml.safe_load((_ROOT / "config.example.yaml").read_text()))
    container = config.resolved_service_container("lobehub", "server")

    assert [port.model_dump() for port in container.ports] == [
        {
            "target": 3210,
            "published": 3210,
            "host_ip": "127.0.0.1",
            "protocol": "tcp",
        }
    ]
    assert container.environment["OPENAI_PROXY_URL"] == "http://10.88.0.1:8003/v1"
    assert [volume.target for volume in container.volumes] == ["/var/lib/codespace/lobehub"]


def test_lobehub_smoke_reproduces_service_contract(tmp_path: Path) -> None:
    podman = tmp_path / "podman"
    events = tmp_path / "events"
    podman.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" >> "$EVENTS"\nif [ "$1" = container ]; then exit 1; fi\n'
    )
    podman.chmod(0o755)

    subprocess.run(  # noqa: S603
        ["/bin/bash", str(_SERVICE / "smoke.sh")],
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "EVENTS": str(events),
            "HOME": str(tmp_path),
        },
        check=True,
        capture_output=True,
    )

    args = events.read_text().splitlines()
    assert "127.0.0.1:3210:3210" in args
    assert f"{tmp_path}/codespace/services/lobehub:/var/lib/codespace/lobehub" in args
    assert "OPENAI_PROXY_URL=http://10.88.0.1:8003/v1" in args
    assert "--device" not in args
    assert "--secret" not in args
