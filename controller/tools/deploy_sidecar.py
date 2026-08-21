"""Deploy the fixed host-level sidecar on every non-local (SSH) host.

Each configured host runs a single ``codespace-sidecar`` container that serves
the shared Atuin server and the image-prewarm cron job (see
``images/sidecar/AGENTS.md``). This out-of-band CLI replicates
``images/sidecar/run-linux.sh`` over the existing Podman transport: it pulls the
fixed image, replaces any same-name container, and starts it on the host network
with the rootful Podman socket bind-mounted and the ``atuin_db_uri`` secret
injected as ``ATUIN_DB_URI``.

Only SSH hosts are targeted. Podman Machine hosts (the macOS ``local`` host) use
the bridge-network launcher ``run-macos.sh`` and are skipped here. The secret
must already be registered on the host (e.g. via ``sync_secrets``); a host
without it is reported and left untouched.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Annotated, Literal

import typer
from podman.domain.containers import Container
from rich.console import Console
from rich.table import Table

from controller.config import CONFIG_PATH, Config, load_config
from controller.container import pull_image, wait_running
from controller.models import PODMAN_SOCKET
from controller.runtime.transport import PodmanTransport

SIDECAR_IMAGE = "ghcr.io/curoky/devspace:codespace-sidecar"
SIDECAR_NAME = "codespace-sidecar"
SIDECAR_SECRET = "atuin_db_uri"  # noqa: S105 - secret name, not a value
SIDECAR_SECRET_ENV = "ATUIN_DB_URI"  # noqa: S105 - env var name, not a value

type Action = Literal["create", "replace"]

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    no_dry_run: Annotated[
        bool,
        typer.Option("--no-dry-run", help="Pull and (re)start the sidecar on every SSH host."),
    ] = False,
) -> None:
    """Show the sidecar plan for every SSH host and optionally deploy it."""
    config = load_config(CONFIG_PATH)
    hosts = _sidecar_hosts(config)
    if not hosts:
        console.print("No SSH hosts configured; the sidecar runs only on non-local hosts.")
        return

    transport = PodmanTransport({host: hc.endpoint() for host, hc in config.hosts.items()})
    try:
        plan, errors = _plan(transport, hosts)

        table = Table()
        table.add_column("Host")
        table.add_column("Sidecar", overflow="fold")
        table.add_column("Action", no_wrap=True)
        for host, action in plan:
            table.add_row(host, SIDECAR_NAME, action)
        console.print(table)

        for error in errors:
            console.print(f"[yellow]Warning:[/yellow] {error}")

        if not no_dry_run:
            console.print(
                f"Dry run: {len(plan)} sidecar(s) to create/replace; pass --no-dry-run to apply."
            )
            return

        applied, apply_errors = _apply(config, transport, [host for host, _ in plan])
        for error in apply_errors:
            console.print(f"[red]Error:[/red] {error}")
        console.print(f"Deployed {applied} sidecar(s).")
    finally:
        transport.close()


def _sidecar_hosts(config: Config) -> list[str]:
    """Return the SSH hosts that host-network sidecars are deployed to."""
    return sorted(host for host, options in config.hosts.items() if options.type == "ssh")


def _plan(
    transport: PodmanTransport,
    hosts: list[str],
) -> tuple[list[tuple[str, Action]], list[str]]:
    plan: list[tuple[str, Action]] = []
    errors: list[str] = []
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_inspect_host, transport, host): host for host in hosts}
        for future in as_completed(futures):
            host = futures[future]
            try:
                has_secret, has_container = future.result()
            except Exception as exc:
                errors.append(f"{host}: {exc}")
                continue
            if not has_secret:
                errors.append(
                    f"{host}: missing podman secret {SIDECAR_SECRET!r}; "
                    "register it first (e.g. with sync_secrets)"
                )
                continue
            plan.append((host, "replace" if has_container else "create"))
    plan.sort(key=lambda item: item[0])
    return plan, errors


def _inspect_host(transport: PodmanTransport, host: str) -> tuple[bool, bool]:
    client = transport.client(host)
    return client.secrets.exists(SIDECAR_SECRET), client.containers.exists(SIDECAR_NAME)


def _apply(
    config: Config,
    transport: PodmanTransport,
    hosts: list[str],
) -> tuple[int, list[str]]:
    applied = 0
    errors: list[str] = []
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(_deploy_host, config, transport, host): host for host in hosts}
        for future in as_completed(futures):
            host = futures[future]
            try:
                future.result()
                applied += 1
            except Exception as exc:
                errors.append(f"{host}: {exc}")
    return applied, errors


def _deploy_host(config: Config, transport: PodmanTransport, host: str) -> None:
    client = transport.client(host)
    if not client.secrets.exists(SIDECAR_SECRET):
        raise RuntimeError(f"missing podman secret {SIDECAR_SECRET!r}")

    pull_image(client, SIDECAR_IMAGE, None)

    if client.containers.exists(SIDECAR_NAME):
        client.containers.get(SIDECAR_NAME).remove(force=True)

    # image-prewarm reaches the host engine over the bind-mounted rootful socket;
    # keep the container-internal path fixed even when the host socket differs.
    socket = config.host_config(host).resolved_podman_socket()
    created = client.containers.run(
        SIDECAR_IMAGE,
        name=SIDECAR_NAME,
        detach=True,
        network_mode="host",
        restart_policy={"Name": "unless-stopped"},
        mounts=[{"type": "bind", "source": socket, "target": PODMAN_SOCKET}],
        secret_env={SIDECAR_SECRET_ENV: SIDECAR_SECRET},
    )
    if not isinstance(created, Container):
        raise TypeError(f"expected Container, got {type(created)}")
    wait_running(created)


if __name__ == "__main__":
    app()
