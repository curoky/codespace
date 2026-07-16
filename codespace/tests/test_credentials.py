"""Tests for credential injection and repo cloning."""

import io
import tarfile

from cryptography.hazmat.primitives.serialization import load_ssh_private_key, load_ssh_public_key

from codespace import shared
from codespace.agent import credentials


class _FakeContainer:
    """Container stub recording exec/put_archive calls for injection tests."""

    def __init__(self, labels: dict[str, str]) -> None:
        self.labels = labels
        self.id = "deadbeef"
        cs_id = labels.get(shared.LABEL_ID, "")
        self.name = shared.container_name(cs_id) if cs_id else ""
        self.execs: list[tuple[list[str], str | None]] = []
        self.archives: list[tuple[str, bytes]] = []

    def exec_run(self, cmd: list[str], *, user: str | None = None) -> tuple[int, bytes]:
        self.execs.append((cmd, user))
        return 0, b""

    def put_archive(self, path: str, data: bytes) -> bool:
        self.archives.append((path, data))
        return True


class _FakeContainers:
    def __init__(self, container: _FakeContainer) -> None:
        self._container = container

    def get(self, name: str) -> _FakeContainer:
        return self._container


class _FakeClient:
    def __init__(self, container: _FakeContainer) -> None:
        self.containers = _FakeContainers(container)


def test_inject_credentials_chowns_and_puts_archive() -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(container)

    credentials.inject_credentials(
        client,
        cs_id="abc",
        private_key="PRIV",
        login_pubkey="ssh-ed25519 LOGIN",
        provider="github",
    )

    # workspace chown (root) happened before archive, ~/.ssh chown after.
    assert (["chown", "-R", "x:x", "/workspace"], "0") in container.execs
    assert container.archives  # credentials were written via put_archive
    path, data = container.archives[0]
    assert path == "/home/x/.ssh"
    names = _tar_names(data)
    assert set(names) == {"repo_id_ed25519", "config.codespace.tmp", "authorized_keys"}
    ssh_config = _tar_member(data, "config.codespace.tmp").decode()
    assert credentials._SSH_CONFIG_BEGIN in ssh_config
    assert "Host github.com" in ssh_config
    assert "StrictHostKeyChecking accept-new" in ssh_config
    assert credentials._SSH_CONFIG_END in ssh_config

    append_cmds = [
        cmd for cmd, user in container.execs if cmd[3:5] == ["append-ssh-config", "/home/x/.ssh"]
    ]
    assert append_cmds
    append_cmd = append_cmds[0]
    assert 'cat "$tmp_block" >> "$tmp_config"' in append_cmd[2]
    assert 'mv "$tmp_config" "$config"' in append_cmd[2]

    ssh_chown = (["chown", "-R", "x:x", "/home/x/.ssh"], "0")
    assert container.execs.count(ssh_chown) == 1
    append_index = next(
        index
        for index, (cmd, user) in enumerate(container.execs)
        if cmd[3:5] == ["append-ssh-config", "/home/x/.ssh"] and user == "0"
    )
    assert append_index < container.execs.index(ssh_chown)


def test_inject_credentials_uses_fixed_user_home_path() -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(container)

    credentials.inject_credentials(
        client,
        cs_id="abc",
        private_key="PRIV",
        login_pubkey="ssh-ed25519 LOGIN",
        provider="github",
    )

    assert container.archives[0][0] == "/home/x/.ssh"


def test_clone_repo_clones_into_repo_name_directory() -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(container)

    credentials.clone_repo(
        client,
        cs_id="abc",
        repo="owner/name",
        provider="github",
    )

    cmd, user = container.execs[-1]
    assert user == "x"
    assert cmd[:2] == ["sh", "-c"]
    assert cmd[-2:] == ["owner/name", "/workspace/name"]
    assert 'git clone "git@$git_host:$repo.git" "$target"' in cmd[2]
    # The injected body is the on-disk resource, not an inline heredoc.
    assert cmd[2] == credentials._load_script("clone_repo.sh")


def test_append_ssh_config_uses_loaded_script_verbatim() -> None:
    container = _FakeContainer(labels={shared.LABEL_ID: "abc"})
    client = _FakeClient(container)

    credentials.inject_credentials(
        client,
        cs_id="abc",
        private_key="PRIV",
        login_pubkey="ssh-ed25519 LOGIN",
        provider="github",
    )

    append_cmd = next(cmd for cmd, _user in container.execs if cmd[3:4] == ["append-ssh-config"])
    assert append_cmd[2] == credentials._load_script("append_ssh_config.sh")


def test_load_script_reads_resource_and_caches() -> None:
    clone = credentials._load_script("clone_repo.sh")
    append = credentials._load_script("append_ssh_config.sh")

    assert clone.startswith("#!/bin/sh")
    assert 'git clone "git@$git_host:$repo.git" "$target"' in clone
    assert append.startswith("#!/bin/sh")
    assert 'mv "$tmp_config" "$config"' in append
    # @cache returns the identical object on repeat lookups.
    assert credentials._load_script("clone_repo.sh") is clone


def test_multi_member_tar_contains_members_with_modes() -> None:
    archive = credentials._multi_member_tar(
        [
            ("repo_id_ed25519", "PRIVATE", 0o600),
            ("config", "cfg", 0o600),
        ]
    )
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r") as tar:
        names = tar.getnames()
        assert names == ["repo_id_ed25519", "config"]
        member = tar.getmember("repo_id_ed25519")
        assert member.mode == 0o600
        extracted = tar.extractfile("repo_id_ed25519")
        assert extracted is not None
        assert extracted.read() == b"PRIVATE"


def test_generate_deploy_keypair_is_valid_and_unique() -> None:
    first = credentials.generate_deploy_keypair()
    second = credentials.generate_deploy_keypair()

    load_ssh_private_key(first.private_openssh.encode(), password=None)
    load_ssh_public_key(first.public_openssh.encode())
    assert first.private_openssh != second.private_openssh
    assert first.public_openssh != second.public_openssh


def _tar_names(data: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        return tar.getnames()


def _tar_member(data: bytes, name: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        extracted = tar.extractfile(name)
        assert extracted is not None
        return extracted.read()
