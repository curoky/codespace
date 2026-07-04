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
    name: Home
    agent_url: http://h:8001
    ssh_host: 10.0.0.5
""",
    )

    cfg = client_config.load_config(path)

    assert cfg.defaults.agent == "home"
    assert cfg.github.token_env == "GITHUB_TOKEN"
    assert cfg.agents["home"].id == "home"
    assert cfg.agents["home"].display_name == "Home"


def test_load_config_reads_create_templates(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _write_config(
        path,
        """
defaults:
  agent: home
  image: img
  extra_repos:
    - owner/default-extra
agents:
  home:
    agent_url: http://h:8001
    ssh_host: 10.0.0.5
  office:
    agent_url: http://o:8001
    ssh_host: 10.0.0.8
templates:
  api:
    name: API Service
    description: Backend service environment
    agent: office
    repo: owner/api
    workspace: backend
    alias: office-api-backend
    image: custom-img
    user: dev
    extra_repos:
      - owner/shared
""",
    )

    cfg = client_config.load_config(path)
    template = cfg.templates["api"]

    assert template.id == "api"
    assert template.display_name == "API Service"
    assert template.agent == "office"
    assert template.repo == "owner/api"
    assert template.workspace == "backend"
    assert template.alias == "office-api-backend"
    assert template.image == "custom-img"
    assert template.user == "dev"
    assert template.extra_repos == ["owner/shared"]


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
    assert client_config.load_config().agents["home"].display_name == "home"


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


def test_github_token_reads_configured_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    monkeypatch.setenv("MY_TOKEN", "secret")

    assert client_config.github_token(client_config.load_config(path)) == "secret"
