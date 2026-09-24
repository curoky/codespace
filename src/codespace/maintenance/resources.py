"""Plan and fill the codespace-resource named volume on every Host."""

from __future__ import annotations

import shlex
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Literal, cast

import typer
from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import APIError, PodmanError
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Column, Table

from codespace.config import CONFIG_PATH, load_config

RESOURCE_VOLUME = "codespace-resource"
_DIGEST_MARKER = ".codespace-resource-digest"
_CLIENT_TIMEOUT = 30 * 60.0
_LOG_TAIL = 2000

type Action = Literal["create", "fill", "skip"]

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("sync")
def _sync(
    apply: Annotated[bool, typer.Option("--apply", help="Apply resource changes.")] = False,
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
    """Inspect and optionally fill the resource volume on every Host."""
    target = console or Console()
    config = load_config(config_path)
    hosts = sorted(config.hosts)
    resource_image = config.project_defaults.resource_image
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.fields[host]}[/bold]"),
        TextColumn("{task.description}"),
        TimeElapsedColumn(),
        console=target,
        transient=True,
        disable=not target.is_terminal,
    )
    tasks = {host: progress.add_task("queued", host=host, total=None) for host in hosts}

    def sync_host(host: str) -> Action:
        task = tasks[host]

        def stage(status: str) -> None:
            progress.update(task, description=status)

        try:
            action = _sync_host(
                host,
                resource_image=resource_image,
                apply=apply,
                force=force,
                stage=stage,
            )
        except BaseException:
            progress.update(task, description="[red]failed[/red]")
            raise
        progress.update(task, description=action, completed=1, total=1)
        return action

    with progress, ThreadPoolExecutor() as executor:
        actions = executor.map(sync_host, hosts)
        states = list(zip(hosts, actions, strict=True))

    table = Table("Host", Column("Action", no_wrap=True))
    for host, action in states:
        table.add_row(host, action)
    target.print(table)

    pending = sum(action != "skip" for _host, action in states)
    if apply:
        target.print(f"Filled {pending} resource volume(s).")
    else:
        target.print(f"Dry run: {pending} volume(s); pass --apply to execute.")


def _sync_host(
    host: str,
    *,
    resource_image: str,
    apply: bool,
    force: bool,
    stage: Callable[[str], None] | None = None,
) -> Action:
    report = stage or (lambda _status: None)
    report("connecting")
    with PodmanClient(
        base_url=f"http+ssh://{host}/run/podman/podman.sock",
        timeout=_CLIENT_TIMEOUT,
    ) as client:
        if apply:
            report("pulling image")
            events = cast(
                "Iterator[dict[str, str]]",
                client.images.pull(resource_image, stream=True, decode=True, policy="always"),
            )
            for event in events:
                if error := event.get("error"):
                    raise PodmanError(f"failed to pull {resource_image}: {error}")

        report("checking volume")
        if not client.volumes.exists(RESOURCE_VOLUME):
            action: Action = "create"
        elif force:
            action = "fill"
        else:
            report("checking digest")
            try:
                exit_code, _detail = _run_helper(
                    client,
                    resource_image,
                    (
                        f"grep -Fqx -- {shlex.quote(_image_digest(client, resource_image))} "
                        f"/dst/{_DIGEST_MARKER}"
                    ),
                    read_only=True,
                )
            except APIError:
                action = "fill"
            else:
                action = "skip" if exit_code == 0 else "fill"

        if not apply or action == "skip":
            return action

        digest = _image_digest(client, resource_image)
        if not client.volumes.exists(RESOURCE_VOLUME):
            report("creating volume")
            client.volumes.create(RESOURCE_VOLUME)
        report("filling volume")
        script = (
            "find /dst -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + "
            "&& cp -a /opt/resource/. /dst/ "
            f"&& printf '%s\\n' {shlex.quote(digest)} > /dst/{_DIGEST_MARKER}"
        )
        exit_code, detail = _run_helper(
            client,
            resource_image,
            script,
            read_only=False,
        )
        if exit_code != 0:
            raise RuntimeError(f"resource fill failed ({exit_code}): {detail}")
        return action


def _image_digest(client: PodmanClient, resource_image: str) -> str:
    digest = client.images.get(resource_image).attrs.get("Digest")
    if not isinstance(digest, str) or not digest:
        raise RuntimeError(f"{resource_image} has no digest")
    return digest


def _run_helper(
    client: PodmanClient,
    resource_image: str,
    script: str,
    *,
    read_only: bool,
) -> tuple[int, str]:
    mode = "ro" if read_only else "rw"
    helper = client.containers.run(
        resource_image,
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
        logs = helper.logs(
            stdout=True,
            stderr=True,
            stream=False,
            timestamps=True,
            tail=_LOG_TAIL,
        )
        raw = logs if isinstance(logs, bytes) else b"".join(logs)
        return exit_code, raw.decode("utf-8", "replace").strip()
    finally:
        helper.remove(force=True)


if __name__ == "__main__":
    app()
