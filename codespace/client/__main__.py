"""Codespace client CLI (create / list / delete).

Talks to the Linux agent over plain HTTP with ``httpx``; the wire contract
lives in :mod:`codespace.shared`.
"""

import subprocess
from pathlib import Path

import httpx
import typer
from github import GithubException
from rich.console import Console
from rich.table import Table

from codespace import shared
from codespace.client import github, ssh_config

app = typer.Typer(help="Lightweight self-hosted codespace client.")

# Local directory holding per-alias login keypairs.
KEY_DIR = Path.home() / ".ssh" / "codespace"
HTTP_TIMEOUT = 30


# --- HTTP helpers ------------------------------------------------------------


def _request(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    """Perform an HTTP request and return ``(status, parsed_json)``.

    4xx/5xx responses are returned rather than raised so callers can inspect the
    ``error`` field the agent returns; a non-JSON body yields an empty dict.
    """
    try:
        resp = httpx.request(method, url, json=body, timeout=HTTP_TIMEOUT)
    except httpx.RequestError as exc:
        raise _fail(f"cannot reach agent: {exc}") from exc
    try:
        return resp.status_code, (resp.json() if resp.content else {})
    except ValueError:
        return resp.status_code, {"error": resp.text or resp.reason_phrase}


def _fail(message: str) -> typer.Exit:
    """Print an error message and return an Exit to raise."""
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    return typer.Exit(code=1)


# --- Key management ----------------------------------------------------------


def _ensure_login_key(alias: str) -> str:
    """Ensure a passwordless ed25519 login keypair exists; return the pubkey.

    Generation is skipped when the key already exists so ``create`` is safe to
    re-run for the same alias.
    """
    KEY_DIR.mkdir(parents=True, exist_ok=True)
    key_path = KEY_DIR / alias
    pub_path = KEY_DIR / f"{alias}.pub"
    if not key_path.exists():
        # Fixed argv (no shell, no user-controlled interpolation); ssh-keygen is
        # resolved from PATH as is conventional for a client-side CLI tool.
        subprocess.run(  # noqa: S603
            ["ssh-keygen", "-t", "ed25519", "-f", str(key_path), "-N", ""],  # noqa: S607
            check=True,
            capture_output=True,
        )
    return pub_path.read_text(encoding="utf-8").strip()


# --- Commands ----------------------------------------------------------------


@app.command()
def create(
    repo: str = typer.Option(..., "--repo", help="Target GitHub repo, 'owner/name'."),
    agent: str = typer.Option(..., "--agent", help="Agent base URL, e.g. http://host:8080."),
    ssh_host: str = typer.Option(
        ..., "--ssh-host", help="Reachable host for ssh to the dev container."
    ),
    token: str = typer.Option(
        ..., "--token", envvar="GITHUB_TOKEN", help="GitHub token (env GITHUB_TOKEN)."
    ),
    image: str = typer.Option(
        "codespace/dev:latest", "--image", help="Dev image satisfying the §3 contract."
    ),
    user: str = typer.Option(
        shared.DEFAULT_CONTAINER_USER, "--user", help="Login user inside the dev image."
    ),
    workspace: str = typer.Option(
        shared.DEFAULT_WORKSPACE, "--workspace", help="Workspace name for persistence."
    ),
    alias: str | None = typer.Option(
        None, "--alias", help="SSH alias; defaults to repo name + workspace."
    ),
) -> None:
    """Create a codespace and register an ssh alias for it.

    The GitHub token stays on the client: the agent returns a deploy public key
    which the client registers on the repo. If registration fails, the client
    rolls back by asking the agent to delete the just-created container.
    """
    if alias is None:
        alias = f"{repo.split('/')[-1]}-{workspace}"

    login_pubkey = _ensure_login_key(alias)
    payload = shared.CreateRequest(
        repo=repo,
        login_pubkey=login_pubkey,
        image=image,
        user=user,
        workspace=workspace,
    )

    status, data = _request("POST", f"{agent.rstrip('/')}/codespaces", body=payload.model_dump())
    if status != 201:
        raise _fail(data.get("error", f"agent returned HTTP {status}"))

    cs = shared.Codespace.model_validate(data)
    if not cs.deploy_public_key:
        _delete_remote(agent, cs.id)
        _remove_login_key(alias)
        raise _fail("agent did not return a deploy public key")

    # Register the deploy key with our own token; on failure roll back the
    # container and the local login key so no orphan is left behind.
    try:
        github.register_deploy_key(token, repo, cs.id, cs.deploy_public_key)
    except GithubException as exc:
        _delete_remote(agent, cs.id)
        _remove_login_key(alias)
        raise _fail(f"failed to register deploy key (rolled back container): {exc}") from exc

    ssh_config.upsert(alias, ssh_host, cs.port, cs.user, cs.id, repo)
    typer.secho(f"codespace ready (id={cs.id}).", fg=typer.colors.GREEN)
    typer.echo(f"connect with: ssh {alias}")


def _delete_remote(agent: str, cs_id: str) -> None:
    """Best-effort request to delete a codespace container on the agent."""
    _request("DELETE", f"{agent.rstrip('/')}/codespaces/{cs_id}")


def _remove_login_key(alias: str) -> None:
    """Delete the local login keypair for ``alias`` (used to clean up rollbacks)."""
    for path in (KEY_DIR / alias, KEY_DIR / f"{alias}.pub"):
        path.unlink(missing_ok=True)


@app.command(name="list")
def list_codespaces(
    agent: str = typer.Option(..., "--agent", help="Agent base URL, e.g. http://host:8080."),
    ssh_host: str = typer.Option(
        "-", "--ssh-host", help="Reachable ssh host to show in the HOST column."
    ),
) -> None:
    """List codespaces managed by the agent."""
    status, data = _request("GET", f"{agent.rstrip('/')}/codespaces")
    if status != 200:
        raise _fail(data.get("error", f"agent returned HTTP {status}"))

    rows = [shared.Codespace.model_validate(item) for item in data]
    table = Table("ID", "REPO", "WORKSPACE", "HOST", "PORT", "STATUS")
    for cs in rows:
        table.add_row(cs.id, cs.repo, cs.workspace, ssh_host, str(cs.port), cs.status or "-")
    Console().print(table)


@app.command()
def delete(
    alias: str = typer.Option(..., "--alias", help="SSH alias to delete."),
    agent: str = typer.Option(..., "--agent", help="Agent base URL, e.g. http://host:8080."),
    token: str = typer.Option(
        ..., "--token", envvar="GITHUB_TOKEN", help="GitHub token (env GITHUB_TOKEN)."
    ),
    cs_id: str | None = typer.Option(
        None, "--id", help="Codespace id; resolved from ssh config when omitted."
    ),
    repo: str | None = typer.Option(
        None, "--repo", help="Repo of the deploy key; resolved from ssh config when omitted."
    ),
    purge: bool = typer.Option(False, "--purge", help="Also delete the workspace directory."),
) -> None:
    """Delete a codespace and clean up local ssh state.

    The codespace id and repo are read from the alias's ssh config block, so the
    user need not remember them (``--id`` / ``--repo`` override when the block is
    missing). The client revokes the GitHub deploy key with its own token before
    asking the agent to remove the container.
    """
    if cs_id is None:
        cs_id = ssh_config.get_id(alias)
    if not cs_id:
        raise _fail(f"cannot resolve codespace id for alias '{alias}'; pass --id")
    if repo is None:
        repo = ssh_config.get_repo(alias)

    # Revoke the deploy key first (client owns the token). Rediscovered by title
    # so it works even without a stored key id.
    if repo:
        try:
            github.delete_deploy_key(token, repo, cs_id)
        except GithubException as exc:
            raise _fail(f"failed to revoke deploy key: {exc}") from exc
    else:
        typer.secho(
            "warning: repo unknown; skipping deploy key revocation (pass --repo).",
            fg=typer.colors.YELLOW,
            err=True,
        )

    url = f"{agent.rstrip('/')}/codespaces/{cs_id}"
    if purge:
        url += "?purge=true"
    status, data = _request("DELETE", url)
    if status != 200:
        raise _fail(data.get("error", f"agent returned HTTP {status}"))

    # Best-effort local cleanup regardless of remote result details.
    ssh_config.remove(alias)
    _remove_login_key(alias)

    resp = shared.DeleteResponse.model_validate(data)
    suffix = " (workspace purged)" if resp.workspace_removed else ""
    typer.secho(f"deleted codespace {cs_id}{suffix}.", fg=typer.colors.GREEN)


if __name__ == "__main__":
    app()
