"""Tests for idempotent ~/.ssh/config block management."""

from pathlib import Path

import pytest

from codespace.client import ssh_config


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the module's ssh config path into a temp file."""
    path = tmp_path / "config"
    monkeypatch.setattr(ssh_config, "SSH_CONFIG_PATH", path)
    return path


def test_upsert_creates_block_with_id(config_path: Path) -> None:
    ssh_config.upsert("myalias", "10.0.0.5", 49207, "dev", "abc123", ["owner/name"])
    content = config_path.read_text()
    assert "Host myalias" in content
    assert "HostName 10.0.0.5" in content
    assert "Port 49207" in content
    assert "User dev" in content
    assert "IdentitiesOnly yes" in content
    assert "HostKeyAlgorithms ssh-ed25519" in content
    assert "UpdateHostKeys no" in content
    assert ssh_config.find_entry(codespace_id="abc123") == ssh_config.SshConfigEntry(
        alias="myalias",
        codespace_id="abc123",
        repos=["owner/name"],
        host="10.0.0.5",
        port=49207,
        user="dev",
    )
    assert ssh_config.get_repos("myalias") == ["owner/name"]


def test_upsert_is_idempotent(config_path: Path) -> None:
    ssh_config.upsert("a", "1.1.1.1", 22, "dev", "id1", ["owner/one"])
    ssh_config.upsert("a", "2.2.2.2", 33, "dev", "id2", ["owner/two"])
    content = config_path.read_text()
    assert content.count("Host a") == 1
    assert "HostName 2.2.2.2" in content
    assert "HostName 1.1.1.1" not in content
    assert ssh_config.find_entry(codespace_id="id2") == ssh_config.SshConfigEntry(
        alias="a",
        codespace_id="id2",
        repos=["owner/two"],
        host="2.2.2.2",
        port=33,
        user="dev",
    )
    assert ssh_config.get_repos("a") == ["owner/two"]


def test_upsert_preserves_other_content(config_path: Path) -> None:
    config_path.write_text("Host existing\n    HostName 9.9.9.9\n")
    ssh_config.upsert("new", "1.2.3.4", 22, "dev", "id", ["owner/name"])
    content = config_path.read_text()
    assert "Host existing" in content
    assert "Host new" in content


def test_remove_deletes_only_target_block(config_path: Path) -> None:
    ssh_config.upsert("keep", "1.1.1.1", 22, "dev", "k", ["owner/keep"])
    ssh_config.upsert("drop", "2.2.2.2", 22, "dev", "d", ["owner/drop"])
    ssh_config.remove("drop")
    content = config_path.read_text()
    assert "Host keep" in content
    assert "Host drop" not in content


def test_remove_absent_alias_is_noop(config_path: Path) -> None:
    ssh_config.remove("nothere")  # must not raise
    assert not config_path.exists() or config_path.read_text() == ""


def test_find_entry_returns_none_when_missing(config_path: Path) -> None:
    assert ssh_config.find_entry(codespace_id="ghost") is None


def test_get_repos_returns_empty_when_missing(config_path: Path) -> None:
    assert ssh_config.get_repos("ghost") == []


def test_list_entries_parses_agent_metadata(config_path: Path) -> None:
    ssh_config.upsert(
        "home-name-default",
        "10.0.0.5",
        49207,
        "dev",
        "abc123",
        ["owner/name"],
        agent_id="home",
        repo="owner/name",
    )

    entries = ssh_config.list_entries()

    assert entries == [
        ssh_config.SshConfigEntry(
            alias="home-name-default",
            codespace_id="abc123",
            repos=["owner/name"],
            agent_id="home",
            repo="owner/name",
            host="10.0.0.5",
            port=49207,
            user="dev",
        )
    ]
    assert ssh_config.find_entry(codespace_id="abc123", agent_id="home") == entries[0]


def test_find_entry_requires_matching_agent_metadata(config_path: Path) -> None:
    ssh_config.upsert("name-default", "10.0.0.5", 49207, "dev", "abc123", ["owner/name"])

    entry = ssh_config.find_entry(codespace_id="abc123", agent_id="home")

    assert entry is None
