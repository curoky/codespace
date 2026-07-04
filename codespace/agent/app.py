"""FastAPI application and routes for the codespace agent.

The agent never talks to GitHub and holds no token: it generates a deploy
keypair, injects the private half into the container and returns the public
half to the client, which owns all GitHub interaction. The agent stays
stateless -- all metadata is read back from podman labels. See DESIGN.md §4/§6.
"""

import secrets

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from loguru import logger
from podman import PodmanClient
from podman.errors import PodmanError
from pydantic import BaseModel, Field

from codespace import shared
from codespace.agent import keys, podman_ops


class AgentConfig(BaseModel):
    """Agent runtime configuration, validated at startup (fail-fast).

    Only host-environment properties live here; caller-side choices (image,
    login user, reachable SSH host) are supplied by the client. Values come from
    the ``serve`` CLI. See DESIGN.md §6.
    """

    workspace_root_host: str = Field(..., description="Host path prefix for workspace bind mounts.")
    podman_uri: str = Field(..., description="Podman service socket URI.")


def _workspace_host_dir(config: AgentConfig, repo: str, workspace: str) -> str:
    """Compute the host workspace directory path passed to podman's bind source."""
    name = shared.workspace_dir_name(repo, workspace)
    root = config.workspace_root_host.rstrip("/")
    return f"{root}/{name}"


def create_app(config: AgentConfig) -> FastAPI:
    """Build the FastAPI app bound to ``config``."""
    app = FastAPI(title="codespace-agent")

    @app.exception_handler(HTTPException)
    def _render_error(_request: object, exc: HTTPException) -> JSONResponse:
        """Render errors as the ``{error}`` body the client expects (DESIGN.md §4)."""
        return JSONResponse(
            status_code=exc.status_code,
            content=shared.ErrorResponse(error=str(exc.detail)).model_dump(),
        )

    def _client() -> PodmanClient:
        return PodmanClient(base_url=config.podman_uri)

    @app.post("/codespaces", status_code=201)
    def create_codespace(req: shared.CreateRequest) -> shared.Codespace:
        cs_id = secrets.token_hex(3)
        workspace_host_dir = _workspace_host_dir(config, req.repo, req.workspace)
        logger.info("creating codespace id={} repo={} workspace={}", cs_id, req.repo, req.workspace)

        # Generate the deploy keypair in memory: the private half is injected
        # into the container, the public half is returned for the client to
        # register with GitHub. The agent never sees a token.
        keypair = keys.generate_deploy_keypair()

        try:
            with _client() as client:
                info = podman_ops.create_container(
                    client,
                    cs_id=cs_id,
                    image=req.image,
                    repo=req.repo,
                    workspace=req.workspace,
                    user=req.user,
                    workspace_host_dir=workspace_host_dir,
                )
                podman_ops.inject_credentials(
                    client,
                    cs_id=cs_id,
                    user=req.user,
                    private_key=keypair.private_openssh,
                    login_pubkey=req.login_pubkey,
                )
        except Exception as exc:
            logger.exception("provisioning codespace {} failed; rolling back", cs_id)
            _rollback(config, cs_id)
            raise HTTPException(
                status_code=500, detail=f"failed to provision codespace: {exc}"
            ) from exc

        logger.info("codespace {} ready on port {}", cs_id, info.port)
        return shared.Codespace(
            id=cs_id,
            port=info.port,
            user=req.user,
            container_id=info.container_id,
            repo=req.repo,
            workspace=req.workspace,
            workspace_dir=shared.workspace_dir_name(req.repo, req.workspace),
            deploy_public_key=keypair.public_openssh,
            status="running",
        )

    @app.get("/codespaces")
    def list_codespaces() -> list[shared.Codespace]:
        with _client() as client:
            containers = podman_ops.list_containers(client)
            return [podman_ops.to_codespace(c) for c in containers]

    @app.delete("/codespaces/{cs_id}")
    def delete_codespace(cs_id: str, purge: bool = Query(False)) -> shared.DeleteResponse:
        with _client() as client:
            container = podman_ops.get_container(client, cs_id)
            if container is None:
                # Idempotent: nothing to delete. The client is responsible for
                # removing the GitHub deploy key (it owns the token).
                logger.info("delete codespace {}: not found, treating as done", cs_id)
                return shared.DeleteResponse(ok=True, workspace_removed=False)

            repo = podman_ops.read_label(container, shared.LABEL_REPO)
            workspace = podman_ops.read_label(container, shared.LABEL_WORKSPACE)

            podman_ops.remove_container(container)

            workspace_removed = False
            if purge and repo and workspace:
                podman_ops.purge_workspace(client, _workspace_host_dir(config, repo, workspace))
                workspace_removed = True

            logger.info("deleted codespace {} (workspace_removed={})", cs_id, workspace_removed)
            return shared.DeleteResponse(ok=True, workspace_removed=workspace_removed)

    return app


def _rollback(config: AgentConfig, cs_id: str) -> None:
    """Best-effort container cleanup after a failed create.

    No GitHub key exists yet at this point (the client registers it only after
    a successful create), so rollback only needs to remove the container.
    """
    try:
        with PodmanClient(base_url=config.podman_uri) as client:
            container = podman_ops.get_container(client, cs_id)
            if container is not None:
                podman_ops.remove_container(container)
    except PodmanError as exc:
        logger.error("rollback: failed to remove container for {}: {}", cs_id, exc)
