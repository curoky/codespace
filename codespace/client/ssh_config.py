"""Idempotent management of a marked block in ``~/.ssh/config``.

Each codespace owns a block delimited by begin/end markers keyed on its alias.
The codespace id is stored as a comment inside the block so ``delete`` can
recover it without local state (see DESIGN.md §5).
"""

import re
from pathlib import Path

SSH_CONFIG_PATH = Path.home() / ".ssh" / "config"


def _begin(alias: str) -> str:
    return f"# >>> codespace {alias} >>>"


def _end(alias: str) -> str:
    return f"# <<< codespace {alias} <<<"


def _render_block(alias: str, host: str, port: int, user: str, cs_id: str, repo: str) -> str:
    """Render the managed block for an alias.

    ``cs_id`` and ``repo`` are stored as comments so ``delete`` can revoke the
    GitHub deploy key (titled ``codespace-<cs_id>`` on ``repo``) without any
    other local state.
    """
    return "\n".join(
        [
            _begin(alias),
            f"# codespace-id: {cs_id}",
            f"# codespace-repo: {repo}",
            f"Host {alias}",
            f"    HostName {host}",
            f"    Port {port}",
            f"    User {user}",
            f"    IdentityFile ~/.ssh/codespace/{alias}",
            "    StrictHostKeyChecking accept-new",
            "    UserKnownHostsFile ~/.ssh/codespace/known_hosts",
            _end(alias),
        ]
    )


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


def upsert(alias: str, host: str, port: int, user: str, cs_id: str, repo: str) -> None:
    """Insert or replace the managed block for ``alias``.

    Any pre-existing block with the same alias is removed first, so repeated
    calls are idempotent. Other content in the file is preserved verbatim.
    """
    content = _strip_block(_read(), alias)
    content = content.rstrip("\n")
    block = _render_block(alias, host, port, user, cs_id, repo)
    new_content = f"{content}\n\n{block}\n" if content else f"{block}\n"
    _write(new_content)


def remove(alias: str) -> None:
    """Remove the managed block for ``alias`` (no-op when absent)."""
    content = _read()
    if not content:
        return
    stripped = _strip_block(content, alias).rstrip("\n")
    _write(f"{stripped}\n" if stripped else "")


def get_id(alias: str) -> str | None:
    """Return the codespace id stored in the alias block, or ``None``."""
    return _get_comment(alias, "codespace-id")


def get_repo(alias: str) -> str | None:
    """Return the repo stored in the alias block, or ``None``."""
    return _get_comment(alias, "codespace-repo")


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
