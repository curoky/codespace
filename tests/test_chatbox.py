"""Chatbox integration configuration."""

from pathlib import Path

import yaml

from codespace.config import Config

_ROOT = Path(__file__).resolve().parents[1]


def test_chatbox_example_targets_sglang_on_the_same_host() -> None:
    config = Config.model_validate(yaml.safe_load((_ROOT / "config.example.yaml").read_text()))
    host = next(iter(set(config.services["chatbox"].hosts) & set(config.services["sglang"].hosts)))
    container = config.resolved_service_container("chatbox", host)
    (chatbox_port,) = container.ports
    (sglang_port,) = config.resolved_service_container("sglang", host).ports

    assert chatbox_port.host_ip == sglang_port.host_ip
    assert container.environment["CHATBOX_API_UPSTREAM"] == (
        f"http://{sglang_port.host_ip}:{sglang_port.published}"
    )
