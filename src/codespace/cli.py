"""Codespace command-line entry point."""

from __future__ import annotations

import typer
import uvicorn

from codespace.maintenance import keys, resources, secrets, workspaces
from codespace.web.app import create_app

app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(secrets.app, name="secrets")
app.add_typer(workspaces.app, name="workspaces")
app.add_typer(keys.app, name="deploy-keys")
app.add_typer(resources.app, name="resources")


@app.command()
def serve() -> None:
    """Run the fixed localhost-only, single-worker Web application."""
    uvicorn.run(create_app(), host="127.0.0.1", port=8003, workers=1)
