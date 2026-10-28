"""Plan and apply Podman secret synchronization."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.table import Column, Table

from codespace.config import CONFIG_PATH, load_config
from codespace.runtime.transport import PodmanTransport

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
    with (
        closing(PodmanTransport(hosts, client_timeout=_CLIENT_TIMEOUT)) as transport,
        ThreadPoolExecutor() as executor,
    ):

        def scan_host(host: str) -> list[tuple[str, str, Action]]:
            client = transport.client(host)
            scanned: list[tuple[str, str, Action]] = []
            for name in sorted(config.secrets):
                action: Action = "replace" if client.secrets.exists(name) else "create"
                scanned.append((host, name, action))
            return scanned

        plans = list(executor.map(scan_host, hosts))
        states = [state for plan in plans for state in plan]

        table = Table(
            "Host",
            Column("Secret", overflow="fold"),
            Column("Action", no_wrap=True),
        )
        for host, name, action in states:
            table.add_row(host, name, action)
        target.print(table)
        if apply:

            def apply_host(plan: list[tuple[str, str, Action]]) -> None:
                for host, name, action in plan:
                    client = transport.client(host)
                    if action == "replace":
                        client.secrets.remove(name)
                    client.secrets.create(name, config.secrets[name].encode())

            list(executor.map(apply_host, plans))

    if apply:
        target.print(f"Applied {len(states)} secret(s).")
    else:
        target.print(f"Dry run: {len(states)} secret(s); pass --apply to execute.")


if __name__ == "__main__":
    app()
