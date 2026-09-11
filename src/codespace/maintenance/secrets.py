"""Plan and apply Podman secret synchronization."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rich.console import Console

from codespace.config import CONFIG_PATH, Config, load_config
from codespace.maintenance import output
from codespace.runtime.transport import PodmanTransport

type Action = Literal["create", "replace"]


@dataclass(frozen=True, slots=True)
class SecretChange:
    host: str
    name: str
    action: Action
    value: str = field(repr=False)


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
        output.render_table(
            target,
            [
                {"header": "Host"},
                {"header": "Secret", "overflow": "fold"},
                {"header": "Action", "no_wrap": True},
            ],
            [(change.host, change.name, change.action) for change in plan],
        )
        output.print_warnings(target, errors)
        if not apply:
            target.print(f"Dry run: {len(plan)} secret(s); pass --apply to execute.")
            return
        applied, apply_errors = _apply(transport, plan)
        output.print_errors(target, apply_errors)
        target.print(f"Applied {applied} secret(s).")
    finally:
        transport.close()


def _plan(
    config: Config,
    transport: PodmanTransport,
) -> tuple[list[SecretChange], list[str]]:
    names = sorted(config.secrets)
    existing_by_host, failures = output.fan_out(
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
    results, failures = output.fan_out(
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
