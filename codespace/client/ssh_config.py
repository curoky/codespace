"""Idempotent management of a marked block in ``~/.ssh/config``.

Each codespace owns a block delimited by begin/end markers keyed on its alias.
The codespace id and repo are stored as comments inside the block so ``delete``
can recover them (and revoke the deploy key) without other local state
(see DESIGN.md §5).
"""

import re
from pathlib import Path

from pydantic import BaseModel, Field

from codespace import shared

SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"


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


def _read() -> str:
    """Read the ssh config file, returning empty string when absent."""
    if not SSH_CONFIG_PATH.exists():
        return ""
    return SSH_CONFIG_PATH.read_text(encoding="utf-8")


def _write(content: str) -> None:
    """Write the ssh config file, ensuring the directory and 0600 perms."""
    SSH_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SSH_CONFIG_PATH.write_text(content, encoding="utf-8")
    SSH_CONFIG_PATH.chmod(0o600)


def _strip_block(content: str, alias: str) -> str:
    """Remove an existing managed block for ``alias`` from ``content``."""
    pattern = re.compile(
        rf"(?:^|\n)?{re.escape(_begin(alias))}.*?{re.escape(_end(alias))}\n?",
        re.DOTALL,
    )
    return pattern.sub("", content)


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
    content = _strip_block(_read(), alias)
    content = content.rstrip("\n")
    block = _render_block(
        alias, host, port, user, cs_id, repos, agent_id=agent_id, repo=repo, provider=provider
    )
    new_content = f"{content}\n\n{block}\n" if content else f"{block}\n"
    _write(new_content)


def remove(alias: str) -> None:
    """Remove the managed block for ``alias`` (no-op when absent)."""
    content = _read()
    if not content:
        return
    stripped = _strip_block(content, alias).rstrip("\n")
    _write(f"{stripped}\n" if stripped else "")


def get_repos(alias: str) -> list[str]:
    """Return the repos stored in the alias block (main + extras), or ``[]``."""
    raw = _get_comment(alias, "codespace-repos")
    return [r for r in raw.split(",") if r] if raw else []


def list_entries() -> list[SshConfigEntry]:
    """Return all codespace-managed SSH config entries."""
    content = _read()
    if not content:
        return []

    entries: list[SshConfigEntry] = []
    pattern = re.compile(
        r"# >>> codespace (?P<alias>.+?) >>>(?P<body>.*?)# <<< codespace (?P=alias) <<<",
        re.DOTALL,
    )
    for match in pattern.finditer(content):
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


def _get_comment(alias: str, key: str) -> str | None:
    """Return the value of a ``# <key>: <value>`` comment inside the block."""
    content = _read()
    if not content:
        return None
    match = re.search(
        rf"{re.escape(_begin(alias))}.*?# {re.escape(key)}:\s*(\S+).*?{re.escape(_end(alias))}",
        content,
        re.DOTALL,
    )
    return match.group(1) if match else None


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
