"""Plan and apply Podman secret synchronization."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Literal

import typer
from rich.console import Console
from rich.table import Column, Table

from codespace.config import CONFIG_PATH, Config, load_config
from codespace.runtime.transport import PodmanTransport

type Action = Literal["create", "replace"]

app = typer.Typer(add_completion=False, no_args_is_help=True)


@dataclass(frozen=True, slots=True)
class SecretChange:
    host: str
    name: str
    action: Action
    value: str = field(repr=False)


@app.command("sync")
def _sync(
    apply: Annotated[bool, typer.Option("--apply", help="Apply the displayed plan.")] = False,
) -> None:
    """Synchronize configured secrets to every Host."""
    sync(apply=apply)


def sync(
    *,
    apply: bool,
    config_path: Path = CONFIG_PATH,
    console: Console | None = None,
) -> None:
    """Show the complete plan, then optionally create or replace secrets."""
    target = console or Console()
    config = load_config(config_path)
    if not config.secrets:
        target.print("No secrets declared in config; nothing to sync.")
        return

    transport = PodmanTransport(config.hosts)
    try:
        plan, errors = _plan(config, transport)
        table = Table(
            "Host",
            Column("Secret", overflow="fold"),
            Column("Action", no_wrap=True),
        )
        for change in plan:
            table.add_row(change.host, change.name, change.action)
        target.print(table)
        for error in errors:
            target.print(f"[yellow]Warning:[/yellow] {error}")
        if not apply:
            target.print(f"Dry run: {len(plan)} secret(s); pass --apply to execute.")
            return
        applied, apply_errors = _apply(transport, plan)
        for error in apply_errors:
            target.print(f"[red]Error:[/red] {error}")
        target.print(f"Applied {applied} secret(s).")
    finally:
        transport.close()


def _fan_out[K, V](
    keys: Iterable[K], work: Callable[[K], V]
) -> tuple[list[tuple[K, V]], list[tuple[K, Exception]]]:
    """Run all planned targets, retaining each target's success or failure."""
    results: list[tuple[K, V]] = []
    failures: list[tuple[K, Exception]] = []
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(work, key): key for key in keys}
        for future in as_completed(futures):
            key = futures[future]
            try:
                results.append((key, future.result()))
            except Exception as exc:
                failures.append((key, exc))
    return results, failures


def _plan(
    config: Config,
    transport: PodmanTransport,
) -> tuple[list[SecretChange], list[str]]:
    names = sorted(config.secrets)
    existing_by_host, failures = _fan_out(
        config.hosts,
        lambda host: _existing_secrets(transport, host, names),
    )
    plan = [
        SecretChange(host, name, "replace" if name in existing else "create", config.secrets[name])
        for host, existing in existing_by_host
        for name in names
    ]
    plan.sort(key=lambda item: (item.host, item.name))
    return plan, [f"{host}: {exc}" for host, exc in failures]


def _existing_secrets(
    transport: PodmanTransport,
    host: str,
    names: list[str],
) -> set[str]:
    client = transport.client(host)
    return {name for name in names if client.secrets.exists(name)}


def _apply(transport: PodmanTransport, plan: list[SecretChange]) -> tuple[int, list[str]]:
    grouped: dict[str, list[SecretChange]] = defaultdict(list)
    for change in plan:
        grouped[change.host].append(change)
    results, failures = _fan_out(
        grouped,
        lambda host: _apply_host(transport, host, grouped[host]),
    )
    applied = sum(count for _host, (count, _errors) in results)
    errors = [
        f"{host}: {error}" for host, (_count, host_errors) in results for error in host_errors
    ]
    errors.extend(f"{host}: {exc}" for host, exc in failures)
    return applied, errors


def _apply_host(
    transport: PodmanTransport,
    host: str,
    changes: list[SecretChange],
) -> tuple[int, list[str]]:
    client = transport.client(host)
    applied = 0
    errors: list[str] = []
    for change in changes:
        try:
            exists = client.secrets.exists(change.name)
            if exists != (change.action == "replace"):
                raise RuntimeError("secret state changed since planning; run sync again")
            if change.action == "replace":
                client.secrets.remove(change.name)
            client.secrets.create(change.name, change.value.encode())
            applied += 1
        except Exception as exc:
            errors.append(f"{change.name}: {exc}")
    return applied, errors


if __name__ == "__main__":
    app()
