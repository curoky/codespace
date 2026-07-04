"""Codespace client CLI (create / list / delete).

Talks to the Linux agent over plain HTTP with ``httpx``; the wire contract
lives in :mod:`codespace.shared`.
"""

import contextlib
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
# Fixed list of extra repos every codespace gets read-only pull access to
# (one ``owner/name`` per line, ``#`` comments allowed).
EXTRA_REPOS_CONFIG = Path.home() / ".config" / "codespace" / "extra-repos"
HTTP_TIMEOUT = 30


def _load_extra_repos() -> list[str]:
    """Read the fixed extra-repos config; missing file yields an empty list."""
    if not EXTRA_REPOS_CONFIG.exists():
        return []
    repos = []
    for line in EXTRA_REPOS_CONFIG.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            repos.append(entry)
    return repos


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
    extra_repo: list[str] = typer.Option(
        [], "--extra-repo", help="Extra read-only repo(s); adds to the fixed config list."
    ),
    alias: str | None = typer.Option(
        None, "--alias", help="SSH alias; defaults to repo name + workspace."
    ),
) -> None:
    """Create a codespace and register an ssh alias for it.

    The GitHub token stays on the client: the agent returns deploy public keys
    (read-write for the main repo, read-only for each extra repo) which the
    client registers on the respective repos. Extra repos come from the fixed
    config (``~/.config/codespace/extra-repos``) plus any ``--extra-repo``. If
    any registration fails, the client rolls back all registered keys, the
    container, and the local login key.
    """
    if alias is None:
        alias = f"{repo.split('/')[-1]}-{workspace}"

    # Merge fixed config with CLI extras; dedupe and drop the main repo.
    extra_repos = list(dict.fromkeys([*_load_extra_repos(), *extra_repo]))
    extra_repos = [r for r in extra_repos if r != repo]

    login_pubkey = _ensure_login_key(alias)
    payload = shared.CreateRequest(
        repo=repo,
        login_pubkey=login_pubkey,
        image=image,
        user=user,
        workspace=workspace,
        extra_repos=extra_repos,
    )

    status, data = _request("POST", f"{agent.rstrip('/')}/codespaces", body=payload.model_dump())
    if status != 201:
        raise _fail(data.get("error", f"agent returned HTTP {status}"))

    cs = shared.Codespace.model_validate(data)
    if not cs.deploy_keys:
        _delete_remote(agent, cs.id)
        _remove_login_key(alias)
        raise _fail("agent did not return any deploy keys")

    # Register each deploy key with our own token; on any failure roll back all
    # keys registered so far, the container, and the local login key.
    registered: list[str] = []
    for key in cs.deploy_keys:
        try:
            github.register_deploy_key(
                token, key.repo, cs.id, key.public_openssh, read_only=key.read_only
            )
            registered.append(key.repo)
        except GithubException as exc:
            for done_repo in registered:
                _revoke_quietly(token, done_repo, cs.id)
            _delete_remote(agent, cs.id)
            _remove_login_key(alias)
            raise _fail(
                f"failed to register deploy key on {key.repo} (rolled back): {exc}"
            ) from exc

    ssh_config.upsert(
        alias, ssh_host, cs.port, cs.user, cs.id, [key.repo for key in cs.deploy_keys]
    )
    typer.secho(f"codespace ready (id={cs.id}).", fg=typer.colors.GREEN)
    if extra_repos:
        typer.echo(f"extra read-only repos: {', '.join(extra_repos)}")
    typer.echo(f"connect with: ssh {alias}")


def _delete_remote(agent: str, cs_id: str) -> None:
    """Best-effort request to delete a codespace container on the agent."""
    _request("DELETE", f"{agent.rstrip('/')}/codespaces/{cs_id}")


def _revoke_quietly(token: str, repo: str, cs_id: str) -> None:
    """Best-effort deploy-key revocation used during create rollback."""
    with contextlib.suppress(GithubException):
        github.delete_deploy_key(token, repo, cs_id)


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
    repo: list[str] = typer.Option(
        [],
        "--repo",
        help="Repo(s) whose deploy key to revoke; resolved from ssh config if omitted.",
    ),
    purge: bool = typer.Option(False, "--purge", help="Also delete the workspace directory."),
) -> None:
    """Delete a codespace and clean up local ssh state.

    The codespace id and repos are read from the alias's ssh config block, so
    the user need not remember them (``--id`` / ``--repo`` override when the
    block is missing). The client revokes every repo's GitHub deploy key with
    its own token before asking the agent to remove the container.
    """
    if cs_id is None:
        cs_id = ssh_config.get_id(alias)
    if not cs_id:
        raise _fail(f"cannot resolve codespace id for alias '{alias}'; pass --id")
    repos = list(repo) if repo else ssh_config.get_repos(alias)

    # Revoke every deploy key first (client owns the token). Rediscovered by
    # title so it works even without stored key ids.
    if repos:
        for r in repos:
            try:
                github.delete_deploy_key(token, r, cs_id)
            except GithubException as exc:
                raise _fail(f"failed to revoke deploy key on {r}: {exc}") from exc
    else:
        typer.secho(
            "warning: repos unknown; skipping deploy key revocation (pass --repo).",
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
