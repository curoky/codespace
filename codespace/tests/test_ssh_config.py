"""Tests for idempotent Codespace SSH config block management."""

import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from codespace.client import ssh_config


@pytest.fixture
def ssh_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Redirect the module's ssh config paths into temp files."""
    main = tmp_path / ".ssh" / "config"
    dedicated = tmp_path / ".ssh" / "codespace" / "ssh_config"
    monkeypatch.setattr(ssh_config, "SSH_CONFIG_PATH", main)
    monkeypatch.setattr(ssh_config, "CODESPACE_SSH_CONFIG_PATH", dedicated)
    return main, dedicated


def test_upsert_creates_dedicated_block_with_id(ssh_paths: tuple[Path, Path]) -> None:
    main_config, dedicated_config = ssh_paths
    ssh_config.upsert("myalias", "10.0.0.5", 49207, "dev", "abc123", ["owner/name"])
    assert ssh_config.CODESPACE_INCLUDE_LINE in main_config.read_text()
    assert "Host myalias" not in main_config.read_text()
    content = dedicated_config.read_text()
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


def test_upsert_renders_ssh_options_inside_block(ssh_paths: tuple[Path, Path]) -> None:
    _main_config, dedicated_config = ssh_paths
    ssh_config.upsert(
        "myalias",
        "10.0.0.5",
        49207,
        "dev",
        "abc123",
        ["owner/name"],
        ssh_options={"ProxyJump": "jump-proxy.example.org"},
    )
    content = dedicated_config.read_text()
    assert "    ProxyJump jump-proxy.example.org" in content
    # options land after the managed directives, before the end marker.
    assert content.index("ProxyJump") > content.index("UpdateHostKeys no")
    assert content.index("ProxyJump") < content.index("# <<< codespace myalias <<<")


def test_upsert_rejects_injectable_ssh_option(ssh_paths: tuple[Path, Path]) -> None:
    with pytest.raises(ValueError, match="ssh_option"):
        ssh_config.upsert(
            "myalias",
            "10.0.0.5",
            49207,
            "dev",
            "abc123",
            ["owner/name"],
            ssh_options={"ProxyJump": "host\n    ProxyCommand rm -rf /"},
        )


def test_upsert_is_idempotent(ssh_paths: tuple[Path, Path]) -> None:
    main_config, dedicated_config = ssh_paths
    ssh_config.upsert("a", "1.1.1.1", 22, "dev", "id1", ["owner/one"])
    ssh_config.upsert("a", "2.2.2.2", 33, "dev", "id2", ["owner/two"])
    assert main_config.read_text().count(ssh_config.CODESPACE_INCLUDE_LINE) == 1
    content = dedicated_config.read_text()
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


def test_upsert_preserves_other_main_config_content(ssh_paths: tuple[Path, Path]) -> None:
    main_config, dedicated_config = ssh_paths
    main_config.parent.mkdir(parents=True)
    main_config.write_text("Host existing\n    HostName 9.9.9.9\n")
    ssh_config.upsert("new", "1.2.3.4", 22, "dev", "id", ["owner/name"])
    main_content = main_config.read_text()
    assert main_content.startswith(f"{ssh_config.CODESPACE_INCLUDE_LINE}\n\n")
    assert "Host existing" in main_content
    assert "Host new" not in main_config.read_text()
    assert "Host new" in dedicated_config.read_text()


def test_remove_deletes_only_target_block(ssh_paths: tuple[Path, Path]) -> None:
    main_config, dedicated_config = ssh_paths
    ssh_config.upsert("keep", "1.1.1.1", 22, "dev", "k", ["owner/keep"])
    ssh_config.upsert("drop", "2.2.2.2", 22, "dev", "d", ["owner/drop"])
    ssh_config.remove("drop")
    content = dedicated_config.read_text()
    assert "Host keep" in content
    assert "Host drop" not in content
    assert ssh_config.CODESPACE_INCLUDE_LINE in main_config.read_text()


def test_remove_absent_alias_is_noop(ssh_paths: tuple[Path, Path]) -> None:
    main_config, dedicated_config = ssh_paths
    ssh_config.remove("nothere")  # must not raise
    assert ssh_config.CODESPACE_INCLUDE_LINE in main_config.read_text()
    assert dedicated_config.exists()
    assert dedicated_config.read_text() == ""


def test_find_entry_returns_none_when_missing(ssh_paths: tuple[Path, Path]) -> None:
    assert ssh_config.find_entry(codespace_id="ghost") is None


def test_get_repos_returns_empty_when_missing(ssh_paths: tuple[Path, Path]) -> None:
    assert ssh_config.get_repos("ghost") == []


def test_list_entries_parses_agent_metadata(ssh_paths: tuple[Path, Path]) -> None:
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


def test_find_entry_requires_matching_agent_metadata(ssh_paths: tuple[Path, Path]) -> None:
    ssh_config.upsert("name-default", "10.0.0.5", 49207, "dev", "abc123", ["owner/name"])

    entry = ssh_config.find_entry(codespace_id="abc123", agent_id="home")

    assert entry is None


def test_migrates_legacy_blocks_from_main_config(ssh_paths: tuple[Path, Path]) -> None:
    main_config, dedicated_config = ssh_paths
    main_config.parent.mkdir(parents=True)
    main_config.write_text(
        "Host existing\n"
        "    HostName 9.9.9.9\n\n"
        "# >>> codespace old >>>\n"
        "# codespace-id: old-id\n"
        "# codespace-repos: owner/old\n"
        "# codespace-provider: gitlab\n"
        "# codespace-agent: home\n"
        "# codespace-repo: owner/old\n"
        "Host old\n"
        "    HostName 10.0.0.5\n"
        "    Port 22\n"
        "    User dev\n"
        "# <<< codespace old <<<\n"
    )

    entries = ssh_config.list_entries()

    main_content = main_config.read_text()
    assert "Host existing" in main_content
    assert "# >>> codespace old >>>" not in main_content
    assert ssh_config.CODESPACE_INCLUDE_LINE in main_content
    assert "# >>> codespace old >>>" in dedicated_config.read_text()
    assert entries == [
        ssh_config.SshConfigEntry(
            alias="old",
            codespace_id="old-id",
            repos=["owner/old"],
            provider="gitlab",
            agent_id="home",
            repo="owner/old",
            host="10.0.0.5",
            port=22,
            user="dev",
        )
    ]


def test_migration_keeps_existing_dedicated_alias(ssh_paths: tuple[Path, Path]) -> None:
    main_config, dedicated_config = ssh_paths
    main_config.parent.mkdir(parents=True)
    dedicated_config.parent.mkdir(parents=True)
    main_config.write_text(
        "# >>> codespace same >>>\n"
        "# codespace-id: old-id\n"
        "# codespace-repos: owner/old\n"
        "Host same\n"
        "    HostName 1.1.1.1\n"
        "    Port 22\n"
        "    User dev\n"
        "# <<< codespace same <<<\n"
    )
    dedicated_config.write_text(
        "# >>> codespace same >>>\n"
        "# codespace-id: new-id\n"
        "# codespace-repos: owner/new\n"
        "Host same\n"
        "    HostName 2.2.2.2\n"
        "    Port 33\n"
        "    User dev\n"
        "# <<< codespace same <<<\n"
    )

    entries = ssh_config.list_entries()

    assert main_config.read_text().count("# >>> codespace same >>>") == 0
    assert dedicated_config.read_text().count("# >>> codespace same >>>") == 1
    assert entries[0].codespace_id == "new-id"
    assert entries[0].host == "2.2.2.2"


def test_migration_skips_duplicate_legacy_aliases(ssh_paths: tuple[Path, Path]) -> None:
    main_config, dedicated_config = ssh_paths
    main_config.parent.mkdir(parents=True)
    main_config.write_text(
        "# >>> codespace same >>>\n"
        "# codespace-id: old-id\n"
        "# codespace-repos: owner/old\n"
        "Host same\n"
        "    HostName 1.1.1.1\n"
        "    Port 22\n"
        "    User dev\n"
        "# <<< codespace same <<<\n\n"
        "# >>> codespace same >>>\n"
        "# codespace-id: duplicate-id\n"
        "# codespace-repos: owner/duplicate\n"
        "Host same\n"
        "    HostName 2.2.2.2\n"
        "    Port 33\n"
        "    User dev\n"
        "# <<< codespace same <<<\n"
    )

    entries = ssh_config.list_entries()

    content = dedicated_config.read_text()
    assert content.count("# >>> codespace same >>>") == 1
    assert entries[0].codespace_id == "old-id"


def test_remove_cleans_legacy_main_block(ssh_paths: tuple[Path, Path]) -> None:
    main_config, _dedicated_config = ssh_paths
    main_config.parent.mkdir(parents=True)
    main_config.write_text(
        "Host existing\n"
        "    HostName 9.9.9.9\n\n"
        "# >>> codespace drop >>>\n"
        "# codespace-id: drop-id\n"
        "# codespace-repos: owner/drop\n"
        "Host drop\n"
        "    HostName 2.2.2.2\n"
        "    Port 22\n"
        "    User dev\n"
        "# <<< codespace drop <<<\n"
    )

    ssh_config.remove("drop")

    main_content = main_config.read_text()
    assert "Host existing" in main_content
    assert "Host drop" not in main_content
    assert ssh_config.CODESPACE_INCLUDE_LINE in main_content


def test_existing_include_is_not_duplicated(ssh_paths: tuple[Path, Path]) -> None:
    main_config, _dedicated_config = ssh_paths
    main_config.parent.mkdir(parents=True)
    main_config.write_text("Include    ~/.ssh/codespace/ssh_config\n")

    ssh_config.upsert("a", "1.1.1.1", 22, "dev", "id", ["owner/name"])

    assert main_config.read_text().lower().count("include") == 1
    assert "~/.ssh/codespace/ssh_config" in main_config.read_text()


def test_existing_include_with_comment_is_not_duplicated(ssh_paths: tuple[Path, Path]) -> None:
    main_config, _dedicated_config = ssh_paths
    main_config.parent.mkdir(parents=True)
    main_config.write_text("Include '~/.ssh/codespace/ssh_config' # codespace\nHost existing\n")

    ssh_config.upsert("a", "1.1.1.1", 22, "dev", "id", ["owner/name"])

    assert main_config.read_text().lower().count("include") == 1


def test_include_is_moved_to_top_level(ssh_paths: tuple[Path, Path]) -> None:
    main_config, _dedicated_config = ssh_paths
    main_config.parent.mkdir(parents=True)
    main_config.write_text("Host existing\n    HostName 9.9.9.9\n")

    ssh_config.upsert("a", "1.1.1.1", 22, "dev", "id", ["owner/name"])

    assert main_config.read_text().splitlines()[:3] == [
        ssh_config.CODESPACE_INCLUDE_LINE,
        "",
        "Host existing",
    ]


@pytest.mark.parametrize(
    "alias",
    [
        "",
        ".",
        "..",
        "ssh_config",
        "known_hosts",
        "bad/name",
        "bad name",
        "bad#name",
        "bad*name",
        "bad?name",
        "bad\nname",
    ],
)
def test_reserved_alias_is_rejected(ssh_paths: tuple[Path, Path], alias: str) -> None:
    with pytest.raises(ValueError, match="invalid or reserved SSH alias"):
        ssh_config.upsert(alias, "1.1.1.1", 22, "dev", "id", ["owner/name"])


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"host": "bad\nhost"}, "host"),
        ({"port": 0}, "port"),
        ({"port": 70000}, "port"),
        ({"user": "bad user"}, "user"),
        ({"cs_id": "bad\nid"}, "codespace_id"),
        ({"repos": ["owner,bad"]}, "repo"),
        ({"agent_id": "bad\nagent"}, "agent_id"),
    ],
)
def test_invalid_rendered_values_are_rejected(
    ssh_paths: tuple[Path, Path], kwargs: dict[str, object], match: str
) -> None:
    values: dict[str, object] = {
        "alias": "valid-alias",
        "host": "1.1.1.1",
        "port": 22,
        "user": "dev",
        "cs_id": "id",
        "repos": ["owner/name"],
        "agent_id": "home",
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=match):
        ssh_config.upsert(**values)  # type: ignore[arg-type]


def test_concurrent_upserts_do_not_lose_blocks(ssh_paths: tuple[Path, Path]) -> None:
    main_config, dedicated_config = ssh_paths

    def write(index: int) -> None:
        ssh_config.upsert(f"alias-{index}", "1.1.1.1", 22, "dev", f"id-{index}", [f"owner/{index}"])

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, range(8)))

    content = dedicated_config.read_text()
    for index in range(8):
        assert f"Host alias-{index}" in content
    assert main_config.read_text().count(ssh_config.CODESPACE_INCLUDE_LINE) == 1


def test_written_config_files_are_private(ssh_paths: tuple[Path, Path]) -> None:
    main_config, dedicated_config = ssh_paths
    ssh_config.upsert("a", "1.1.1.1", 22, "dev", "id", ["owner/name"])

    assert stat.S_IMODE(main_config.stat().st_mode) == 0o600
    assert stat.S_IMODE(dedicated_config.stat().st_mode) == 0o600
