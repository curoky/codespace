"""Plan and fill the codespace-resource named volume on every Host."""

from __future__ import annotations

import shlex
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Annotated, Literal, cast

import typer
from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import APIError, PodmanError
from rich.console import Console
from rich.table import Column, Table

from codespace.config import CONFIG_PATH, load_config

RESOURCE_VOLUME = "codespace-resource"
RESOURCE_IMAGE = "ghcr.io/curoky/codespace:workspace-resource"
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
    with ThreadPoolExecutor() as executor:
        actions = executor.map(partial(_sync_host, apply=apply, force=force), hosts)
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


def _sync_host(host: str, *, apply: bool, force: bool) -> Action:
    with PodmanClient(
        base_url=f"http+ssh://{host}/run/podman/podman.sock",
        timeout=_CLIENT_TIMEOUT,
    ) as client:
        if not client.volumes.exists(RESOURCE_VOLUME):
            action: Action = "create"
        elif force:
            action = "fill"
        else:
            try:
                exit_code, _detail = _run_helper(
                    client,
                    f"grep -Fqx -- {shlex.quote(_image_digest(client))} /dst/{_DIGEST_MARKER}",
                    read_only=True,
                )
            except APIError:
                action = "fill"
            else:
                action = "skip" if exit_code == 0 else "fill"

        if not apply or action == "skip":
            return action

        events = cast(
            "Iterator[dict[str, str]]",
            client.images.pull(RESOURCE_IMAGE, stream=True, decode=True, policy="always"),
        )
        for event in events:
            if error := event.get("error"):
                raise PodmanError(f"failed to pull {RESOURCE_IMAGE}: {error}")

        digest = _image_digest(client)
        if not client.volumes.exists(RESOURCE_VOLUME):
            client.volumes.create(RESOURCE_VOLUME)
        script = (
            "find /dst -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + "
            "&& cp -a /opt/resource/. /dst/ "
            f"&& printf '%s\\n' {shlex.quote(digest)} > /dst/{_DIGEST_MARKER}"
        )
        exit_code, detail = _run_helper(client, script, read_only=False)
        if exit_code != 0:
            raise RuntimeError(f"resource fill failed ({exit_code}): {detail}")
        return action


def _image_digest(client: PodmanClient) -> str:
    digest = client.images.get(RESOURCE_IMAGE).attrs.get("Digest")
    if not isinstance(digest, str) or not digest:
        raise RuntimeError(f"{RESOURCE_IMAGE} has no digest")
    return digest


def _run_helper(client: PodmanClient, script: str, *, read_only: bool) -> tuple[int, str]:
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
