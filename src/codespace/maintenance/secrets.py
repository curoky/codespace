"""Plan and apply Podman secret synchronization."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Annotated, Literal

import typer
from podman import PodmanClient
from rich.console import Console
from rich.table import Column, Table

from codespace.config import CONFIG_PATH, load_config

_CLIENT_TIMEOUT = 30 * 60.0

type Action = Literal["create", "replace"]

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("sync")
def _sync(
    apply: Annotated[bool, typer.Option("--apply", help="Apply secret changes.")] = False,
) -> None:
    """Synchronize configured secrets to every Host."""
    sync(apply=apply)


def sync(
    *,
    apply: bool,
    config_path: Path = CONFIG_PATH,
    console: Console | None = None,
) -> None:
    """Inspect and optionally create or replace configured secrets."""
    target = console or Console()
    config = load_config(config_path)
    if not config.secrets:
        target.print("No secrets declared in config; nothing to sync.")
        return

    hosts = sorted(config.hosts)
    with ThreadPoolExecutor() as executor:
        actions = executor.map(
            partial(_sync_host, configured=config.secrets, apply=apply),
            hosts,
        )
        states = [
            (host, name, action)
            for host, host_actions in zip(hosts, actions, strict=True)
            for name, action in host_actions
        ]

    table = Table(
        "Host",
        Column("Secret", overflow="fold"),
        Column("Action", no_wrap=True),
    )
    for host, name, action in states:
        table.add_row(host, name, action)
    target.print(table)
    if apply:
        target.print(f"Applied {len(states)} secret(s).")
    else:
        target.print(f"Dry run: {len(states)} secret(s); pass --apply to execute.")


def _sync_host(
    host: str,
    *,
    configured: dict[str, str],
    apply: bool,
) -> list[tuple[str, Action]]:
    actions: list[tuple[str, Action]] = []
    with PodmanClient(
        base_url=f"http+ssh://{host}/run/podman/podman.sock",
        timeout=_CLIENT_TIMEOUT,
    ) as client:
        for name in sorted(configured):
            action: Action = "replace" if client.secrets.exists(name) else "create"
            actions.append((name, action))
            if not apply:
                continue
            if action == "replace":
                client.secrets.remove(name)
            client.secrets.create(name, configured[name].encode())
    return actions


if __name__ == "__main__":
    app()
