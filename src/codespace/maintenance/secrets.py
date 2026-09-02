"""Plan and apply Podman secret synchronization."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from rich.console import Console

from codespace.config import CONFIG_PATH, Config, load_config
from codespace.maintenance import output
from codespace.runtime.transport import PodmanTransport

type Action = Literal["create", "replace"]


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

    transport = PodmanTransport({host: value.endpoint() for host, value in config.hosts.items()})
    try:
        plan, errors = _plan(config, transport)
        output.render_table(
            target,
            [
                {"header": "Host"},
                {"header": "Secret", "overflow": "fold"},
                {"header": "Action", "no_wrap": True},
            ],
            plan,
        )
        output.print_warnings(target, errors)
        if not apply:
            target.print(f"Dry run: {len(plan)} secret(s); pass --apply to execute.")
            return
        applied, apply_errors = _apply(config, transport)
        output.print_errors(target, apply_errors)
        target.print(f"Applied {applied} secret(s).")
    finally:
        transport.close()


def _plan(
    config: Config,
    transport: PodmanTransport,
) -> tuple[list[tuple[str, str, Action]], list[str]]:
    names = sorted(config.secrets)
    existing_by_host, failures = output.fan_out(
        config.hosts,
        lambda host: _existing_secrets(transport, host, names),
    )
    plan: list[tuple[str, str, Action]] = [
        (host, name, "replace" if name in existing else "create")
        for host, existing in existing_by_host
        for name in names
    ]
    plan.sort(key=lambda item: (item[0], item[1]))
    return plan, [f"{host}: {exc}" for host, exc in failures]


def _existing_secrets(
    transport: PodmanTransport,
    host: str,
    names: list[str],
) -> set[str]:
    client = transport.client(host)
    return {name for name in names if client.secrets.exists(name)}


def _apply(config: Config, transport: PodmanTransport) -> tuple[int, list[str]]:
    results, failures = output.fan_out(
        config.hosts,
        lambda host: _apply_host(transport, host, config.secrets),
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
    values: dict[str, str],
) -> tuple[int, list[str]]:
    client = transport.client(host)
    applied = 0
    errors: list[str] = []
    for name in sorted(values):
        try:
            if client.secrets.exists(name):
                client.secrets.remove(name)
            client.secrets.create(name, values[name].encode())
            applied += 1
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    return applied, errors
