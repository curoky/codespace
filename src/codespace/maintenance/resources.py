"""Plan and fill the codespace-resource named volume on every Host.

The resource image (``ghcr.io/curoky/codespace:workspace-resource``) stages its
payload under ``/opt/resource`` on top of a shell- and coreutils-bearing base, so
``codespace resources sync`` fills the named volume by running the image directly
and copying that subtree into the volume mounted at ``/dst``. Every Workspace then
mounts the volume read-only at ``/opt/resource``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

import typer
from podman import PodmanClient
from podman.domain.containers import Container
from rich.console import Console
from rich.table import Column, Table

from codespace.config import CONFIG_PATH, Config, load_config
from codespace.runtime import container as runtime
from codespace.runtime.transport import PodmanTransport

RESOURCE_VOLUME = "codespace-resource"
RESOURCE_IMAGE = "ghcr.io/curoky/codespace:workspace-resource"
_READY_MARKER = ".codespace-resource-ready"

type Action = Literal["create", "fill", "skip"]

app = typer.Typer(add_completion=False, no_args_is_help=True)


@dataclass(frozen=True, slots=True)
class ResourceChange:
    host: str
    action: Action


@app.command("sync")
def _sync(
    apply: Annotated[bool, typer.Option("--apply", help="Apply the displayed plan.")] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Refill even if the volume is already populated.")
    ] = False,
) -> None:
    """Create and fill the codespace-resource volume on every Host."""
    sync(apply=apply, force=force)


def sync(
    *,
    apply: bool,
    force: bool = False,
    config_path: Path = CONFIG_PATH,
    console: Console | None = None,
) -> None:
    """Show the plan, then optionally create and fill the resource volume."""
    target = console or Console()
    config = load_config(config_path)

    transport = PodmanTransport(config.hosts)
    try:
        plan, errors = _plan(config, transport, force)
        table = Table("Host", Column("Action", no_wrap=True))
        for change in plan:
            table.add_row(change.host, change.action)
        target.print(table)
        for error in errors:
            target.print(f"[yellow]Warning:[/yellow] {error}")
        pending = [change for change in plan if change.action != "skip"]
        if not apply:
            target.print(f"Dry run: {len(pending)} volume(s); pass --apply to execute.")
            return
        applied, apply_errors = _apply(transport, pending)
        for error in apply_errors:
            target.print(f"[red]Error:[/red] {error}")
        target.print(f"Filled {applied} resource volume(s).")
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
    force: bool,
) -> tuple[list[ResourceChange], list[str]]:
    states, failures = _fan_out(
        config.hosts,
        lambda host: _plan_host(transport, host, force),
    )
    plan = [ResourceChange(host, action) for host, action in states]
    plan.sort(key=lambda item: item.host)
    return plan, [f"{host}: {exc}" for host, exc in failures]


def _plan_host(transport: PodmanTransport, host: str, force: bool) -> Action:
    client = transport.client(host)
    if not client.volumes.exists(RESOURCE_VOLUME):
        return "create"
    if force or not _is_filled(client):
        return "fill"
    return "skip"


def _apply(
    transport: PodmanTransport,
    plan: list[ResourceChange],
) -> tuple[int, list[str]]:
    results, failures = _fan_out(
        [change.host for change in plan],
        lambda host: _apply_host(transport, host),
    )
    applied = sum(1 for _host, host_errors in results if not host_errors)
    errors = [f"{host}: {error}" for host, host_errors in results for error in host_errors]
    errors.extend(f"{host}: {exc}" for host, exc in failures)
    return applied, errors


def _apply_host(transport: PodmanTransport, host: str) -> list[str]:
    client = transport.client(host)
    try:
        runtime.pull_image(client, RESOURCE_IMAGE, None, policy="always")
        if not client.volumes.exists(RESOURCE_VOLUME):
            client.volumes.create(RESOURCE_VOLUME)
        _fill(client)
    except Exception as exc:
        return [str(exc)]
    return []


def _is_filled(client: PodmanClient) -> bool:
    # The volume's Mountpoint is a path on the remote Host, unreadable over the API, so probe
    # the ready marker from inside the resource image itself with the volume mounted.
    exit_code, _detail = _run_helper(client, f"test -f /dst/{_READY_MARKER}", read_only=True)
    return exit_code == 0


def _fill(client: PodmanClient) -> None:
    # The resource image stages the payload at /opt/resource; copy that subtree into the volume.
    script = f"rm -rf /dst/* && cp -a /opt/resource/. /dst/ && touch /dst/{_READY_MARKER}"
    exit_code, detail = _run_helper(client, script, read_only=False)
    if exit_code != 0:
        raise RuntimeError(f"resource fill failed ({exit_code}): {detail}")


def _run_helper(client: PodmanClient, script: str, *, read_only: bool) -> tuple[int, str]:
    """Run one throwaway resource-image container with the volume mounted at /dst."""
    mode = "ro" if read_only else "rw"
    helper = client.containers.run(
        RESOURCE_IMAGE,
        name=None,
        entrypoint=["/bin/sh"],
        command=["-c", script],
        detach=True,
        user="0",
        security_opt=["disable"],
        volumes={RESOURCE_VOLUME: {"bind": "/dst", "mode": mode}},
    )
    if not isinstance(helper, Container):
        raise RuntimeError("expected a detached resource container")
    try:
        exit_code = helper.wait()
        return exit_code, runtime.container_logs(helper).strip()
    finally:
        helper.remove(force=True)


if __name__ == "__main__":
    app()
