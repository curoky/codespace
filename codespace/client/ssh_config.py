"""Idempotent management of Codespace SSH config blocks.

Each codespace owns a block delimited by begin/end markers keyed on its alias.
The codespace id and repo are stored as comments inside the block so ``delete``
can recover them (and revoke the deploy key) without other local state
(see DESIGN.md §9).
"""

import re
from pathlib import Path

from pydantic import BaseModel, Field

from codespace import shared

SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"
CODESPACE_SSH_CONFIG_PATH = Path.home() / ".ssh" / "codespace" / "ssh_config"
CODESPACE_INCLUDE_LINE = "Include ~/.ssh/codespace/ssh_config"
RESERVED_ALIASES = {"", ".", "..", "ssh_config", "known_hosts"}


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
    """Write an ssh config file, ensuring its directory and 0600 perms."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


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
    return re.search(
        rf"{re.escape(_begin(alias))}.*?{re.escape(_end(alias))}",
        content,
        re.DOTALL,
    ) is not None


def _include_targets() -> set[str]:
    """Return accepted Include targets for the dedicated Codespace config."""
    return {"~/.ssh/codespace/ssh_config", str(CODESPACE_SSH_CONFIG_PATH)}


def _has_codespace_include(content: str) -> bool:
    """Return whether ``content`` already includes the dedicated config."""
    targets = _include_targets()
    for line in content.splitlines():
        parts = line.strip().split()
        if (
            len(parts) == 2
            and parts[0].lower() == "include"
            and parts[1].strip("'\"") in targets
        ):
            return True
    return False


def ensure_include() -> None:
    """Ensure the main ssh config includes the dedicated Codespace config."""
    content = _read(SSH_CONFIG_PATH)
    if _has_codespace_include(content):
        if SSH_CONFIG_PATH.exists():
            SSH_CONFIG_PATH.chmod(0o600)
        return
    stripped = content.rstrip("\n")
    new_content = (
        f"{stripped}\n\n{CODESPACE_INCLUDE_LINE}\n"
        if stripped
        else f"{CODESPACE_INCLUDE_LINE}\n"
    )
    _write(SSH_CONFIG_PATH, new_content)


def _migrate_legacy_blocks_from_main_config() -> None:
    """Move legacy managed blocks from the main ssh config into the dedicated file."""
    main_content = _read(SSH_CONFIG_PATH)
    legacy_blocks = _extract_blocks(main_content)
    if not legacy_blocks:
        return

    dedicated_content = _read(CODESPACE_SSH_CONFIG_PATH)
    dedicated = dedicated_content.rstrip("\n")
    for alias, block in legacy_blocks:
        if not _has_block(dedicated_content, alias):
            dedicated = f"{dedicated}\n\n{block}" if dedicated else block

    _write(CODESPACE_SSH_CONFIG_PATH, f"{dedicated.rstrip()}\n" if dedicated else "")
    main_without_blocks = _strip_all_blocks(main_content).rstrip("\n")
    _write(SSH_CONFIG_PATH, f"{main_without_blocks}\n" if main_without_blocks else "")


def _ensure_layout() -> None:
    """Ensure legacy blocks are migrated and the main config includes the dedicated file."""
    _migrate_legacy_blocks_from_main_config()
    ensure_include()


def _validate_alias(alias: str) -> None:
    """Reject aliases that would collide with files in ``~/.ssh/codespace``."""
    if alias in RESERVED_ALIASES or "/" in alias:
        raise ValueError(f"invalid or reserved SSH alias: {alias!r}")


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
    _ensure_layout()
    content = _read(CODESPACE_SSH_CONFIG_PATH)
    stripped = _strip_block(content, alias).rstrip("\n")
    _write(CODESPACE_SSH_CONFIG_PATH, f"{stripped}\n" if stripped else "")

    main_content = _read(SSH_CONFIG_PATH)
    main_stripped = _strip_block(main_content, alias).rstrip("\n")
    if main_stripped != main_content.rstrip("\n"):
        _write(SSH_CONFIG_PATH, f"{main_stripped}\n" if main_stripped else "")
        ensure_include()


def get_repos(alias: str) -> list[str]:
    """Return the repos stored in the alias block (main + extras), or ``[]``."""
    for entry in list_entries():
        if entry.alias == alias:
            return entry.repos
    return []


def list_entries() -> list[SshConfigEntry]:
    """Return all codespace-managed SSH config entries."""
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
