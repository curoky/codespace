"""Codespace agent CLI (``serve``).

Validates configuration then launches the FastAPI app under uvicorn. See
DESIGN.md §6.
"""

import typer
import uvicorn

from codespace.agent.app import AgentConfig, create_app

app = typer.Typer(help="Lightweight self-hosted codespace agent (Podman-out-of-Podman).")


@app.callback()
def _main() -> None:
    """Keep ``serve`` an explicit subcommand.

    Without a callback, typer treats a single-command app as a bare program and
    drops the subcommand name, so ``... serve`` would fail with "unexpected extra
    argument (serve)". The callback forces multi-command mode.
    """


@app.command()
def serve(
    workspace_root_host: str = typer.Option(
        ...,
        "--workspace-root-host",
        help="Host path prefix for workspace bind mounts (interpreted by host podman).",
    ),
    podman_uri: str = typer.Option(..., "--podman-uri", help="Podman service socket URI."),
    host: str = typer.Option("0.0.0.0", "--host", help="HTTP bind address."),
    port: int = typer.Option(8001, "--port", help="HTTP bind port."),
) -> None:
    """Run the agent HTTP service."""
    config = AgentConfig(
        workspace_root_host=workspace_root_host,
        podman_uri=podman_uri,
    )
    uvicorn.run(create_app(config), host=host, port=port)


if __name__ == "__main__":
    app()
