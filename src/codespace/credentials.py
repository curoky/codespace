"""Resolve macOS provider credentials from the personal csecret store."""

from __future__ import annotations

import subprocess
from pathlib import Path

from codespace.workspaces import GitProvider


def load_tokens() -> dict[GitProvider, str]:
    """Read the canonical provider keys once without exposing command output."""
    script = (
        Path.home() / "workspace/codespace/platform/container/workspace/tools/csecret/csecret.sh"
    )
    providers: tuple[GitProvider, ...] = ("github", "gitlab")
    tokens: dict[GitProvider, str] = {}
    for provider in providers:
        key = f"codespace_{provider}_token"
        error = f"cannot load {provider} token from csecret key {key!r}"
        try:
            result = subprocess.run(  # noqa: S603
                [str(script), "get", key],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
                check=False,
            )
        except OSError, subprocess.TimeoutExpired, UnicodeError:
            raise RuntimeError(error) from None
        if result.returncode != 0 or not result.stdout.strip():
            raise RuntimeError(error)
        tokens[provider] = result.stdout
    return tokens
