"""Chatbox packages its Web client with a same-origin SGLang proxy."""

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
    assert "codespace:service-s6" in dockerfile
    assert "apt-get install -y --no-install-recommends gettext-base nginx" in dockerfile
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

    assert "CHATBOX_API_UPSTREAM=http://10.88.0.1:8003" in dockerfile
    assert "location /v1/" in nginx
    assert "listen 8080;" in nginx
    assert "proxy_buffering off;" in nginx
    assert "proxy_pass ${CHATBOX_API_UPSTREAM};" in nginx
    assert "try_files $uri $uri/ /index.html;" in nginx
    assert "EXPOSE" not in dockerfile
    assert (_SERVICE / "rootfs/etc/s6/s6-rc.d/nginx/type").read_text().strip() == "longrun"
    assert (_SERVICE / "rootfs/etc/s6/s6-rc.d/nginx/notification-fd").read_text().strip() == "3"
    assert (_SERVICE / "rootfs/etc/s6/s6-rc.d/default/contents.d/nginx").is_file()


def test_chatbox_example_uses_gateway_and_targets_sglang() -> None:
    config = Config.model_validate(yaml.safe_load((_ROOT / "config.example.yaml").read_text()))
    container = config.resolved_service_container("chatbox", "gpu-host")

    assert [port.model_dump() for port in container.ports] == [
        {
            "target": 8080,
            "published": 3212,
            "host_ip": "10.88.0.1",
            "protocol": "tcp",
        }
    ]
    assert container.environment["CHATBOX_API_UPSTREAM"] == "http://10.88.0.1:8003"
    assert not container.secrets
    assert config.service_tunnel_ports("chatbox", "gpu-host") == [3212]
