"""Create every declared Podman secret on every configured host.

The control plane never creates secrets during environment creation: it only
checks that a referenced secret already exists (see ``container.create_container``).
This out-of-band CLI reads the plaintext values from the top-level ``secrets``
block of the fixed config and registers all of them on every host. Existing
same-name secrets are replaced so the config value wins.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.table import Table

from controller.config import CONFIG_PATH, Config, load_config
from controller.runtime.transport import PodmanTransport

type Action = Literal["create", "replace"]

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    no_dry_run: Annotated[
        bool,
        typer.Option("--no-dry-run", help="Create or replace the Podman secrets."),
    ] = False,
) -> None:
    """Show the declared secrets on every host and optionally register them."""
    config = load_config(CONFIG_PATH)
    if not config.secrets:
        console.print("No secrets declared in config; nothing to sync.")
        return

    transport = PodmanTransport({host: hc.endpoint() for host, hc in config.hosts.items()})
    try:
        plan, errors = _plan(config, transport)

        table = Table()
        table.add_column("Host")
        table.add_column("Secret", overflow="fold")
        table.add_column("Action", no_wrap=True)
        for host, name, action in plan:
            table.add_row(host, name, action)
        console.print(table)

        for error in errors:
            console.print(f"[yellow]Warning:[/yellow] {error}")

        if not no_dry_run:
            console.print(
                f"Dry run: {len(plan)} secret(s) to create/replace; pass --no-dry-run to apply."
            )
            return

        applied, apply_errors = _apply(config, transport)
        for error in apply_errors:
            console.print(f"[red]Error:[/red] {error}")
        console.print(f"Applied {applied} secret(s).")
    finally:
        transport.close()


def _plan(
    config: Config,
    transport: PodmanTransport,
) -> tuple[list[tuple[str, str, Action]], list[str]]:
    names = sorted(config.secrets)
    plan: list[tuple[str, str, Action]] = []
    errors: list[str] = []
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_existing_secrets, transport, host, names): host
            for host in config.hosts
        }
        for future in as_completed(futures):
            host = futures[future]
            try:
                existing = future.result()
            except Exception as exc:
                errors.append(f"{host}: {exc}")
                continue
            for name in names:
                plan.append((host, name, "replace" if name in existing else "create"))
    plan.sort(key=lambda item: (item[0], item[1]))
    return plan, errors


def _existing_secrets(transport: PodmanTransport, host: str, names: list[str]) -> set[str]:
    client = transport.client(host)
    return {name for name in names if client.secrets.exists(name)}


def _apply(config: Config, transport: PodmanTransport) -> tuple[int, list[str]]:
    applied = 0
    errors: list[str] = []
    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_apply_host, transport, host, config.secrets): host
            for host in config.hosts
        }
        for future in as_completed(futures):
            host = futures[future]
            host_applied, host_errors = future.result()
            applied += host_applied
            errors.extend(f"{host}: {error}" for error in host_errors)
    return applied, errors


def _apply_host(
    transport: PodmanTransport,
    host: str,
    values: dict[str, str],
) -> tuple[int, list[str]]:
    client = transport.client(host)
    applied = 0
    errors: list[str] = []
    for name in sorted(values):
        try:
            if client.secrets.exists(name):
                client.secrets.remove(name)
            client.secrets.create(name, values[name].encode("utf-8"))
            applied += 1
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return applied, errors


if __name__ == "__main__":
    app()
