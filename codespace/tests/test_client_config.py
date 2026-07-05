"""Tests for Web GUI YAML config loading."""

from pathlib import Path

import pytest

from codespace.client import config as client_config


def _write_config(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def test_load_config_reads_yaml_profiles(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _write_config(
        path,
        """
defaults:
  agent: home
  image: img
agents:
  home:
    agent_url: http://h:8001
    ssh_host: 10.0.0.5
""",
    )

    cfg = client_config.load_config(path)

    assert cfg.defaults.agent == "home"
    assert cfg.agents["home"].id == "home"
    assert cfg.agents["home"].ssh_host == "10.0.0.5"
    assert cfg.agents["home"].ssh_proxy_host is None
    assert cfg.agents["home"].ssh_proxy is False


def test_load_config_rejects_ssh_proxy_without_proxy_host(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _write_config(
        path,
        """
defaults:
  agent: home
  image: img
agents:
  home:
    agent_url: http://127.0.0.1:8001
    ssh_host: dev-host
    ssh_proxy: true
""",
    )

    with pytest.raises(ValueError, match="ssh_proxy_host is required"):
        client_config.load_config(path)


def test_load_config_accepts_distinct_ssh_proxy_host(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _write_config(
        path,
        """
defaults:
  agent: home
  image: img
agents:
  home:
    agent_url: http://127.0.0.1:8001
    ssh_host: dev-container-host
    ssh_proxy: true
    ssh_proxy_host: bastion-host
""",
    )

    cfg = client_config.load_config(path)

    assert cfg.agents["home"].ssh_host == "dev-container-host"
    assert cfg.agents["home"].ssh_proxy_host == "bastion-host"
    assert cfg.agents["home"].ssh_proxy is True


def test_load_config_reads_create_templates(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _write_config(
        path,
        """
defaults:
  agent: home
  image: img
agents:
  home:
    agent_url: http://h:8001
    ssh_host: 10.0.0.5
  office:
    agent_url: http://o:8001
    ssh_host: 10.0.0.8
templates:
  api:
    description: Backend service environment
    agent: office
    repo: owner/api
    image: custom-img
""",
    )

    cfg = client_config.load_config(path)
    template = cfg.templates["api"]

    assert template.id == "api"
    assert template.agent == "office"
    assert template.repo == "owner/api"
    assert template.image == "custom-img"


def test_load_config_rejects_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _write_config(
        path,
        """
defaults:
  agent: home
  image: img
github:
  token_env: MY_TOKEN
agents:
  home:
    agent_url: http://h:8001
    ssh_host: 10.0.0.5
""",
    )

    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        client_config.load_config(path)


def test_load_config_rejects_template_with_unknown_agent(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _write_config(
        path,
        """
defaults:
  agent: home
  image: img
agents:
  home:
    agent_url: http://h:8001
    ssh_host: 10.0.0.5
templates:
  api:
    agent: missing
    repo: owner/api
""",
    )

    with pytest.raises(ValueError, match="references unknown agent"):
        client_config.load_config(path)


def test_load_config_uses_env_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "from-env.yaml"
    _write_config(
        path,
        """
defaults:
  agent: home
  image: img
agents:
  home:
    agent_url: http://h:8001
    ssh_host: 10.0.0.5
""",
    )
    monkeypatch.setenv(client_config.CONFIG_ENV, str(path))

    assert client_config.resolve_config_path() == path
    assert client_config.load_config().agents["home"].id == "home"


def test_load_config_rejects_missing_default_agent(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _write_config(
        path,
        """
defaults:
  agent: missing
  image: img
agents:
  home:
    agent_url: http://h:8001
    ssh_host: 10.0.0.5
""",
    )

    with pytest.raises(ValueError, match=r"defaults\.agent"):
        client_config.load_config(path)
