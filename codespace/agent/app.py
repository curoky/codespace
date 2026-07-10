"""FastAPI application and routes for the codespace agent.

The agent never talks to a Git provider and holds no token: it generates a
deploy keypair, injects the private half into the container and returns the
public half to the client, which owns provider interaction. Runtime metadata is
read back from podman labels. See DESIGN.md "Agent 创建流程".

This module wires config, the operation store and the provisioner into HTTP
routes; the create flow itself lives in :mod:`codespace.agent.service` and
podman work in :mod:`codespace.agent.containers` / :mod:`.credentials`.
"""

import secrets
from typing import cast

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from loguru import logger
from podman import PodmanClient
from podman.errors import NotFound

from codespace import shared
from codespace.agent import containers, credentials
from codespace.agent.config import AgentConfig, workspace_host_dir
from codespace.agent.operations import OperationStore
from codespace.agent.service import CodespaceProvisioner

__all__ = ["AgentConfig", "create_app"]


def create_app(config: AgentConfig) -> FastAPI:
    """Build the FastAPI app bound to ``config``."""
    app = FastAPI(title="codespace-agent")
    operations = OperationStore()

    def _client() -> PodmanClient:
        return PodmanClient(base_url=config.podman_uri)

    provisioner = CodespaceProvisioner(config, operations, _client)

    @app.exception_handler(HTTPException)
    def _render_error(_request: object, exc: HTTPException) -> JSONResponse:
        """Render errors as the ``{error}`` body the client expects (DESIGN.md §4)."""
        return JSONResponse(
            status_code=exc.status_code,
            content=shared.ErrorResponse(error=str(exc.detail)).model_dump(),
        )

    @app.post("/codespaces", status_code=202)
    def create_codespace(
        req: shared.CreateRequest, background_tasks: BackgroundTasks
    ) -> shared.CreateOperation:
        operation_id = secrets.token_hex(6)
        cs_id = secrets.token_hex(8)
        operation = operations.create(operation_id)
        background_tasks.add_task(provisioner.provision, operation_id, cs_id, req)
        return operation

    @app.get("/operations/{operation_id}")
    def get_operation(operation_id: str) -> shared.CreateOperation:
        operation = operations.get(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="operation not found")
        return operation

    @app.get("/codespaces")
    def list_codespaces() -> list[shared.Codespace]:
        with _client() as client:
            managed = containers.list_containers(client)
            return [containers.to_codespace(c) for c in managed]

    @app.delete("/codespaces/{cs_id}")
    def delete_codespace(cs_id: str, purge: bool = Query(False)) -> shared.DeleteResponse:
        with _client() as client:
            container = containers.get_container(client, cs_id)
            if container is None:
                # Idempotent: nothing to delete. The client is responsible for
                # removing provider deploy keys (it owns the token).
                logger.info("delete codespace {}: not found, treating as done", cs_id)
                return shared.DeleteResponse(ok=True, workspace_removed=False)

            repo = containers.read_label(container, shared.LABEL_REPO)
            template = containers.read_label(
                container, shared.LABEL_TEMPLATE, shared.DEFAULT_TEMPLATE
            )
            instance = containers.read_label(
                container, shared.LABEL_INSTANCE, shared.DEFAULT_INSTANCE
            )

            workspace_removed = False
            if purge and repo and template and instance:
                containers.stop_container(container)
                containers.purge_workspace(
                    client, workspace_host_dir(config, repo, template, instance)
                )
                workspace_removed = True

            containers.remove_container(container)

            logger.info("deleted codespace {} (workspace_removed={})", cs_id, workspace_removed)
            return shared.DeleteResponse(ok=True, workspace_removed=workspace_removed)

    @app.post("/codespaces/{cs_id}/clone")
    def clone_codespace_repo(cs_id: str) -> shared.CloneRepoResponse:
        with _client() as client:
            container = containers.get_container(client, cs_id)
            if container is None:
                raise HTTPException(status_code=404, detail="codespace not found")

            repo = containers.read_label(container, shared.LABEL_REPO)
            provider = containers.read_label(
                container, shared.LABEL_PROVIDER, shared.DEFAULT_GIT_PROVIDER
            )
            user = containers.read_label(
                container, shared.LABEL_USER, shared.DEFAULT_CONTAINER_USER
            )
            if not repo:
                raise HTTPException(status_code=500, detail="codespace repo label is missing")

            try:
                credentials.clone_repo(
                    client,
                    cs_id=cs_id,
                    user=user,
                    repo=repo,
                    provider=cast(shared.GitProvider, provider),
                )
            except NotFound as exc:
                if containers.get_container(client, cs_id) is None:
                    logger.info("clone repo for codespace {} aborted: container was deleted", cs_id)
                    raise HTTPException(status_code=404, detail="codespace not found") from exc
                logger.warning("clone repo for codespace {} hit podman not found: {}", cs_id, exc)
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            except Exception as exc:
                logger.exception("clone repo for codespace {} failed", cs_id)
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            return shared.CloneRepoResponse(ok=True)

    return app
