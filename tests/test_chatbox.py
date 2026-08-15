"""Chatbox packages its Web client with a same-origin SGLang proxy."""

import os
import subprocess
from pathlib import Path

import yaml

from codespace.config import Config

_ROOT = Path(__file__).resolve().parents[1]
_SERVICE = _ROOT / "platform/container/services/chatbox"


def test_chatbox_image_pins_upstream_and_build_toolchain() -> None:
    dockerfile = (_SERVICE / "Dockerfile").read_text()

    assert "node:22.23.2-bookworm-slim" in dockerfile
    assert "ARG CHATBOX_VERSION=v1.23.2" in dockerfile
    assert "pnpm@10.33.0" in dockerfile
    assert "pnpm install --frozen-lockfile" in dockerfile
    assert "CHATBOX_BUILD_PLATFORM=web CHATBOX_ELECTRON_VITE_TARGET=renderer" in dockerfile
    assert "pnpm exec electron-vite build" in dockerfile
    assert "find release/app/dist/renderer -type f -name '*.map' -delete" in dockerfile
    assert "nginx:1.30.4-alpine-slim" in dockerfile
    assert "release/app/dist/renderer/" in dockerfile


def test_chatbox_defaults_target_local_sglang_without_login() -> None:
    patch = (_SERVICE / "defaults.patch").read_text()

    assert "custom-provider-codespace-sglang" in patch
    assert "Qwen/Qwen3.8-Flash-Next-FP8" in patch
    assert "`${globalThis.location?.origin || 'http://localhost:3212'}/v1`" in patch
    assert "apiKey: 'local'" in patch
    assert "allowReportingAndTracking: false" in patch


def test_chatbox_nginx_serves_spa_and_proxies_streaming_api() -> None:
    dockerfile = (_SERVICE / "Dockerfile").read_text()
    nginx = (_SERVICE / "default.conf.template").read_text()

    assert "NGINX_ENVSUBST_FILTER=^CHATBOX_API_UPSTREAM$" in dockerfile
    assert "location /v1/" in nginx
    assert "proxy_buffering off;" in nginx
    assert "proxy_pass ${CHATBOX_API_UPSTREAM};" in nginx
    assert "try_files $uri $uri/ /index.html;" in nginx


def test_chatbox_example_is_loopback_only_and_targets_sglang() -> None:
    config = Config.model_validate(yaml.safe_load((_ROOT / "config.example.yaml").read_text()))
    container = config.resolved_service_container("chatbox", "gpu-host")

    assert [port.model_dump() for port in container.ports] == [
        {
            "target": 3212,
            "published": 3212,
            "host_ip": "127.0.0.1",
            "protocol": "tcp",
        }
    ]
    assert container.environment["CHATBOX_API_UPSTREAM"] == "http://10.88.0.1:8003"
    assert not container.secrets
    assert config.service_tunnel_ports("chatbox", "gpu-host") == [3212]


def test_chatbox_smoke_reproduces_service_contract(tmp_path: Path) -> None:
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
    assert "127.0.0.1:3212:3212" in args
    assert "CHATBOX_API_UPSTREAM=http://10.88.0.1:8003" in args
    assert "--volume" not in args
    assert "--device" not in args
    assert "--secret" not in args
