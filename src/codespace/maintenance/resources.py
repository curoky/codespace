"""Plan and fill the codespace-resource named volume on every Host.

The resource image (``ghcr.io/curoky/codespace:workspace-resource``) is a
payload-only ``scratch`` image whose contents back the named Podman volume
mounted read-only at ``/opt/resource`` in every Workspace. The payload image has
no shell, so a coreutils-bearing helper image performs the copy with the payload
mounted as an image source and the volume mounted as the destination.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from podman import PodmanClient
from podman.domain.containers import Container
from rich.console import Console
from rich.table import Column

from codespace import maintenance
from codespace.config import CONFIG_PATH, Config, load_config
from codespace.runtime import container as runtime
from codespace.runtime.transport import PodmanTransport

RESOURCE_VOLUME = "codespace-resource"
RESOURCE_IMAGE = "ghcr.io/curoky/codespace:workspace-resource"
_READY_MARKER = ".codespace-resource-ready"

type Action = Literal["create", "fill", "skip"]


@dataclass(frozen=True, slots=True)
class ResourceChange:
    host: str
    action: Action


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
        maintenance.render_table(
            target,
            ["Host", Column("Action", no_wrap=True)],
            [(change.host, change.action) for change in plan],
        )
        maintenance.print_errors(target, errors, level="Warning")
        pending = [change for change in plan if change.action != "skip"]
        if not apply:
            target.print(f"Dry run: {len(pending)} volume(s); pass --apply to execute.")
            return
        applied, apply_errors = _apply(config, transport, pending)
        maintenance.print_errors(target, apply_errors)
        target.print(f"Filled {applied} resource volume(s).")
    finally:
        transport.close()


def _plan(
    config: Config,
    transport: PodmanTransport,
    force: bool,
) -> tuple[list[ResourceChange], list[str]]:
    states, failures = maintenance.fan_out(
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
    config: Config,
    transport: PodmanTransport,
    plan: list[ResourceChange],
) -> tuple[int, list[str]]:
    results, failures = maintenance.fan_out(
        [change.host for change in plan],
        lambda host: _apply_host(config, transport, host),
    )
    applied = sum(1 for _host, host_errors in results if not host_errors)
    errors = [f"{host}: {error}" for host, host_errors in results for error in host_errors]
    errors.extend(f"{host}: {exc}" for host, exc in failures)
    return applied, errors


def _apply_host(config: Config, transport: PodmanTransport, host: str) -> list[str]:
    client = transport.client(host)
    try:
        runtime.pull_image(client, RESOURCE_IMAGE, None, policy="always")
        if not client.volumes.exists(RESOURCE_VOLUME):
            client.volumes.create(RESOURCE_VOLUME)
        _fill(client, config.workspace_helper_image(host))
    except Exception as exc:
        return [str(exc)]
    return []


def _is_filled(client: PodmanClient) -> bool:
    volume = client.volumes.get(RESOURCE_VOLUME)
    mountpoint = volume.attrs.get("Mountpoint")
    return bool(mountpoint) and Path(mountpoint, _READY_MARKER).exists()


def _fill(client: PodmanClient, helper_image: str) -> None:
    script = f"rm -rf /dst/* && cp -a /src/. /dst/ && touch /dst/{_READY_MARKER}"
    helper = client.containers.run(
        helper_image,
        name=None,
        entrypoint=["/bin/sh"],
        command=["-c", script],
        detach=True,
        user="0",
        security_opt=["disable"],
        mounts=[
            {"type": "image", "source": RESOURCE_IMAGE, "target": "/src", "read_only": True},
            {"type": "volume", "source": RESOURCE_VOLUME, "target": "/dst", "read_only": False},
        ],
    )
    if not isinstance(helper, Container):
        raise RuntimeError("expected a detached resource-fill container")
    try:
        exit_code = helper.wait()
        if exit_code != 0:
            detail = runtime.container_logs(helper).strip()
            raise RuntimeError(f"resource fill failed ({exit_code}): {detail}")
    finally:
        helper.remove(force=True)
