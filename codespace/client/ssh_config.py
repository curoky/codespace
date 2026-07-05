"""Idempotent management of Codespace SSH config blocks.

Each codespace owns a block delimited by begin/end markers keyed on its alias.
The codespace id and repo are stored as comments inside the block so ``delete``
can recover them (and revoke the deploy key) without other local state
(see DESIGN.md §9).
"""

import fcntl
import os
import re
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

from pydantic import BaseModel, Field

from codespace import shared

SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"
CODESPACE_SSH_CONFIG_PATH = Path.home() / ".ssh" / "codespace" / "ssh_config"
CODESPACE_INCLUDE_LINE = "Include ~/.ssh/codespace/ssh_config"
RESERVED_ALIASES = {"", ".", "..", "ssh_config", "known_hosts"}
_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_THREAD_LOCK = threading.RLock()


class SshConfigEntry(BaseModel, frozen=True):
    """Parsed metadata from one managed codespace SSH config block."""

    alias: str
    codespace_id: str | None = None
    repos: list[str] = Field(default_factory=list)
    provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER
    agent_id: str | None = None
    repo: str | None = None
    host: str | None = None
    port: int | None = None
    user: str | None = None


def _begin(alias: str) -> str:
    return f"# >>> codespace {alias} >>>"


def _end(alias: str) -> str:
    return f"# <<< codespace {alias} <<<"


def _render_block(
    alias: str,
    host: str,
    port: int,
    user: str,
    cs_id: str,
    repos: list[str],
    *,
    agent_id: str | None = None,
    repo: str | None = None,
    provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER,
) -> str:
    """Render the managed block for an alias.

    ``cs_id`` and ``repos`` (comma-separated) are stored as comments so
    ``delete`` can revoke every GitHub deploy key (titled ``codespace-<cs_id>``
    on each repo) without any other local state.
    """
    lines = [
        _begin(alias),
        f"# codespace-id: {cs_id}",
        f"# codespace-repos: {','.join(repos)}",
        f"# codespace-provider: {provider}",
    ]
    if agent_id:
        lines.append(f"# codespace-agent: {agent_id}")
    if repo:
        lines.append(f"# codespace-repo: {repo}")
    lines.extend(
        [
            f"Host {alias}",
            f"    HostName {host}",
            f"    Port {port}",
            f"    User {user}",
            f"    IdentityFile ~/.ssh/codespace/{alias}",
            "    IdentitiesOnly yes",
            "    HostKeyAlgorithms ssh-ed25519",
            "    StrictHostKeyChecking accept-new",
            "    UserKnownHostsFile ~/.ssh/codespace/known_hosts",
            "    UpdateHostKeys no",
            _end(alias),
        ]
    )
    return "\n".join(lines)


def _read(path: Path) -> str:
    """Read the ssh config file, returning empty string when absent."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write(path: Path, content: str) -> None:
    """Atomically write an ssh config file, ensuring its directory and 0600 perms."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    tmp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as tmp:
            tmp_name = tmp.name
            tmp.write(content)
            tmp.flush()
            os.fsync(tmp.fileno())
        Path(tmp_name).chmod(0o600)
        Path(tmp_name).replace(path)
        _fsync_dir(path.parent)
    finally:
        if tmp_name:
            with suppress(FileNotFoundError):
                Path(tmp_name).unlink()


def _fsync_dir(path: Path) -> None:
    """Best-effort fsync for a directory after an atomic rename."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


@contextmanager
def _layout_lock() -> Iterator[None]:
    """Serialize read-modify-write operations across local processes."""
    with _THREAD_LOCK:
        lock_dir = CODESPACE_SSH_CONFIG_PATH.parent
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_dir.chmod(0o700)
        lock_path = lock_dir / ".lock"
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            lock_path.chmod(0o600)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _strip_block(content: str, alias: str) -> str:
    """Remove an existing managed block for ``alias`` from ``content``."""
    pattern = re.compile(
        rf"(?:^|\n)?{re.escape(_begin(alias))}.*?{re.escape(_end(alias))}\n?",
        re.DOTALL,
    )
    return pattern.sub("", content)


def _block_pattern() -> re.Pattern[str]:
    """Pattern matching one managed Codespace block."""
    return re.compile(
        r"(?P<block># >>> codespace (?P<alias>.+?) >>>.*?# <<< codespace (?P=alias) <<<)\n?",
        re.DOTALL,
    )


def _extract_blocks(content: str) -> list[tuple[str, str]]:
    """Extract managed blocks as ``(alias, block)`` pairs."""
    return [
        (match.group("alias"), match.group("block").rstrip("\n"))
        for match in _block_pattern().finditer(content)
    ]


def _strip_all_blocks(content: str) -> str:
    """Remove every managed Codespace block from ``content``."""
    return _block_pattern().sub("", content)


def _has_block(content: str, alias: str) -> bool:
    """Return whether ``content`` contains a managed block for ``alias``."""
    return (
        re.search(
            rf"{re.escape(_begin(alias))}.*?{re.escape(_end(alias))}",
            content,
            re.DOTALL,
        )
        is not None
    )


def _include_targets() -> set[str]:
    """Return accepted Include targets for the dedicated Codespace config."""
    return {"~/.ssh/codespace/ssh_config", str(CODESPACE_SSH_CONFIG_PATH)}


def _line_includes_codespace_config(line: str) -> bool:
    """Return whether one Include line targets the dedicated Codespace config."""
    content = line.split("#", 1)[0].strip()
    parts = content.split()
    if not parts or parts[0].lower() != "include":
        return False
    targets = _include_targets()
    return any(part.strip("'\"") in targets for part in parts[1:])


def _has_codespace_include(content: str) -> bool:
    """Return whether ``content`` already includes the dedicated config."""
    return any(_line_includes_codespace_config(line) for line in content.splitlines())


def _with_global_include(content: str) -> str:
    """Place the Codespace Include at top-level so OpenSSH always sees it."""
    lines = [line for line in content.splitlines() if not _line_includes_codespace_config(line)]
    body = "\n".join(lines).strip("\n")
    return f"{CODESPACE_INCLUDE_LINE}\n\n{body}\n" if body else f"{CODESPACE_INCLUDE_LINE}\n"


def _ensure_include_unlocked() -> None:
    """Ensure the main ssh config includes the dedicated file; caller holds lock."""
    content = _read(SSH_CONFIG_PATH)
    new_content = _with_global_include(content)
    if content == new_content:
        if SSH_CONFIG_PATH.exists():
            SSH_CONFIG_PATH.chmod(0o600)
        return
    _write(SSH_CONFIG_PATH, new_content)


def ensure_include() -> None:
    """Ensure the main ssh config includes the dedicated Codespace config."""
    with _layout_lock():
        _ensure_include_unlocked()


def _migrate_legacy_blocks_from_main_config() -> None:
    """Move legacy managed blocks from the main ssh config into the dedicated file."""
    main_content = _read(SSH_CONFIG_PATH)
    legacy_blocks = _extract_blocks(main_content)
    if not legacy_blocks:
        return

    dedicated_content = _read(CODESPACE_SSH_CONFIG_PATH)
    dedicated = dedicated_content.rstrip("\n")
    seen_aliases = {alias for alias, _block in _extract_blocks(dedicated_content)}
    for alias, block in legacy_blocks:
        if alias not in seen_aliases:
            dedicated = f"{dedicated}\n\n{block}" if dedicated else block
            seen_aliases.add(alias)

    _write(CODESPACE_SSH_CONFIG_PATH, f"{dedicated.rstrip()}\n" if dedicated else "")
    main_without_blocks = _strip_all_blocks(main_content).rstrip("\n")
    _write(SSH_CONFIG_PATH, f"{main_without_blocks}\n" if main_without_blocks else "")


def _ensure_layout() -> None:
    """Ensure legacy blocks are migrated and the main config includes the dedicated file."""
    _migrate_legacy_blocks_from_main_config()
    _ensure_include_unlocked()


def _validate_alias(alias: str) -> None:
    """Reject aliases that would collide with files in ``~/.ssh/codespace``."""
    if alias in RESERVED_ALIASES or not _ALIAS_RE.fullmatch(alias):
        raise ValueError(f"invalid or reserved SSH alias: {alias!r}")


def _reject_newline(value: str, field: str) -> None:
    if "\n" in value or "\r" in value:
        raise ValueError(f"invalid SSH config {field}: must not contain newlines")


def _validate_config_values(
    *,
    host: str,
    port: int,
    user: str,
    cs_id: str,
    repos: list[str],
    agent_id: str | None,
    repo: str | None,
) -> None:
    """Reject values that would generate invalid or injectable SSH config."""
    if not 1 <= port <= 65535:
        raise ValueError(f"invalid SSH port: {port!r}")
    for field, value in {"host": host, "user": user, "codespace_id": cs_id}.items():
        if not value:
            raise ValueError(f"invalid SSH config {field}: must not be empty")
        _reject_newline(value, field)
    if any(char.isspace() for char in user):
        raise ValueError(f"invalid SSH config user: {user!r}")
    if agent_id is not None:
        _reject_newline(agent_id, "agent_id")
    if repo is not None:
        _reject_newline(repo, "repo")
    for item in repos:
        _reject_newline(item, "repo")
        if "," in item:
            raise ValueError(f"invalid SSH config repo: {item!r}")


def upsert(
    alias: str,
    host: str,
    port: int,
    user: str,
    cs_id: str,
    repos: list[str],
    *,
    agent_id: str | None = None,
    repo: str | None = None,
    provider: shared.GitProvider = shared.DEFAULT_GIT_PROVIDER,
) -> None:
    """Insert or replace the managed block for ``alias``.

    Any pre-existing block with the same alias is removed first, so repeated
    calls are idempotent. Other content in the file is preserved verbatim.
    """
    _validate_alias(alias)
    _validate_config_values(
        host=host,
        port=port,
        user=user,
        cs_id=cs_id,
        repos=repos,
        agent_id=agent_id,
        repo=repo,
    )
    with _layout_lock():
        _ensure_layout()
        content = _strip_block(_read(CODESPACE_SSH_CONFIG_PATH), alias)
        content = content.rstrip("\n")
        block = _render_block(
            alias, host, port, user, cs_id, repos, agent_id=agent_id, repo=repo, provider=provider
        )
        new_content = f"{content}\n\n{block}\n" if content else f"{block}\n"
        _write(CODESPACE_SSH_CONFIG_PATH, new_content)


def remove(alias: str) -> None:
    """Remove the managed block for ``alias`` (no-op when absent)."""
    with _layout_lock():
        _ensure_layout()
        content = _read(CODESPACE_SSH_CONFIG_PATH)
        stripped = _strip_block(content, alias).rstrip("\n")
        _write(CODESPACE_SSH_CONFIG_PATH, f"{stripped}\n" if stripped else "")

        main_content = _read(SSH_CONFIG_PATH)
        main_stripped = _strip_block(main_content, alias).rstrip("\n")
        if main_stripped != main_content.rstrip("\n"):
            _write(SSH_CONFIG_PATH, f"{main_stripped}\n" if main_stripped else "")
            _ensure_include_unlocked()


def get_repos(alias: str) -> list[str]:
    """Return the repos stored in the alias block (main + extras), or ``[]``."""
    for entry in list_entries():
        if entry.alias == alias:
            return entry.repos
    return []


def list_entries() -> list[SshConfigEntry]:
    """Return all codespace-managed SSH config entries."""
    with _layout_lock():
        _ensure_layout()
        return _parse_entries(_read(CODESPACE_SSH_CONFIG_PATH))


def _parse_entries(content: str) -> list[SshConfigEntry]:
    """Parse managed SSH config entries from ``content``."""
    if not content:
        return []

    entries: list[SshConfigEntry] = []
    for match in re.finditer(
        r"# >>> codespace (?P<alias>.+?) >>>(?P<body>.*?)# <<< codespace (?P=alias) <<<",
        content,
        re.DOTALL,
    ):
        alias = match.group("alias")
        body = match.group("body")
        entries.append(
            SshConfigEntry(
                alias=alias,
                codespace_id=_comment_from_body(body, "codespace-id"),
                repos=_repos_from_body(body),
                provider=_provider_from_body(body),
                agent_id=_comment_from_body(body, "codespace-agent"),
                repo=_comment_from_body(body, "codespace-repo"),
                host=_directive_from_body(body, "HostName"),
                port=_port_from_body(body),
                user=_directive_from_body(body, "User"),
            )
        )
    return entries


def find_entry(*, codespace_id: str, agent_id: str | None = None) -> SshConfigEntry | None:
    """Find the SSH config entry for a codespace id."""
    matches = [entry for entry in list_entries() if entry.codespace_id == codespace_id]
    if agent_id is not None:
        exact = [entry for entry in matches if entry.agent_id == agent_id]
        return exact[0] if len(exact) == 1 else None
    return matches[0] if len(matches) == 1 else None


def _comment_from_body(body: str, key: str) -> str | None:
    match = re.search(rf"^# {re.escape(key)}:\s*(\S+)\s*$", body, re.MULTILINE)
    return match.group(1) if match else None


def _directive_from_body(body: str, key: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(key)}\s+(\S+)\s*$", body, re.MULTILINE)
    return match.group(1) if match else None


def _repos_from_body(body: str) -> list[str]:
    raw = _comment_from_body(body, "codespace-repos")
    return [repo for repo in raw.split(",") if repo] if raw else []


def _provider_from_body(body: str) -> shared.GitProvider:
    raw = _comment_from_body(body, "codespace-provider")
    return "gitlab" if raw == "gitlab" else shared.DEFAULT_GIT_PROVIDER


def _port_from_body(body: str) -> int | None:
    raw = _directive_from_body(body, "Port")
    return int(raw) if raw and raw.isdigit() else None
