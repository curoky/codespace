"""Chatbox integration configuration."""

from pathlib import Path

import yaml

from codespace.config import Config

_ROOT = Path(__file__).resolve().parents[1]
_START_SCRIPT = _ROOT / "platform/container/services/chatbox/rootfs/opt/chatbox/serve.sh"


def test_chatbox_startup_targets_sglang_on_the_same_host() -> None:
    config = Config.model_validate(yaml.safe_load((_ROOT / "config.example.yaml").read_text()))
    host = next(iter(set(config.services["chatbox"].hosts) & set(config.services["sglang"].hosts)))
    container = config.resolved_service_container("chatbox", host)

    assert container.environment == {}
    assert (
        "export CHATBOX_API_UPSTREAM=http://codespace-service-sglang:8080"
        in _START_SCRIPT.read_text()
    )
    assert container.ports == []
    assert config.service_tunnel_ports("chatbox") == [8080, 8008]
