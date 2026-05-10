"""Codespace command-line entry point."""

from __future__ import annotations

from typing import Annotated

import typer
import uvicorn

from codespace.maintenance import keys, secrets, workspaces
from codespace.web.app import create_app

app = typer.Typer(add_completion=False, no_args_is_help=True)
secrets_app = typer.Typer(add_completion=False)
workspaces_app = typer.Typer(add_completion=False)
deploy_keys_app = typer.Typer(add_completion=False)
app.add_typer(secrets_app, name="secrets")
app.add_typer(workspaces_app, name="workspaces")
app.add_typer(deploy_keys_app, name="deploy-keys")


@app.command()
def serve() -> None:
    """Run the fixed localhost-only, single-worker Web application."""
    uvicorn.run(create_app(), host="127.0.0.1", port=8003, workers=1)


@secrets_app.command("sync")
def sync_secrets(
    apply: Annotated[bool, typer.Option("--apply", help="Apply the displayed plan.")] = False,
) -> None:
    """Synchronize configured secrets to every Host."""
    secrets.sync(apply=apply)


@workspaces_app.command("prune")
def prune_workspaces(
    apply: Annotated[bool, typer.Option("--apply", help="Apply the displayed plan.")] = False,
) -> None:
    """Delete Workspace data without a matching managed container."""
    workspaces.prune(apply=apply)


@deploy_keys_app.command("prune")
def prune_deploy_keys(
    apply: Annotated[bool, typer.Option("--apply", help="Apply the displayed plan.")] = False,
) -> None:
    """Delete provider deploy keys unused by managed Workspaces."""
    keys.prune(apply=apply)
