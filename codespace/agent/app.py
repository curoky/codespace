"""FastAPI application and routes for the codespace agent.

The agent never talks to GitHub and holds no token: it generates a deploy
keypair, injects the private half into the container and returns the public
half to the client, which owns all GitHub interaction. The agent stays
stateless -- all metadata is read back from podman labels. See DESIGN.md §4/§6.
"""

import secrets
from threading import Lock, Thread

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from loguru import logger
from podman import PodmanClient
from podman.errors import NotFound, PodmanError
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


def _workspace_host_dir(config: AgentConfig, repo: str, template: str, instance: str) -> str:
    """Compute the host workspace directory path passed to podman's bind source."""
    name = shared.workspace_dir_name(repo, template, instance)
    root = config.workspace_root_host.rstrip("/")
    return f"{root}/{name}"


def create_app(config: AgentConfig) -> FastAPI:
    """Build the FastAPI app bound to ``config``."""
    app = FastAPI(title="codespace-agent")
    operations: dict[str, shared.CreateOperation] = {}
    operations_lock = Lock()

    @app.exception_handler(HTTPException)
    def _render_error(_request: object, exc: HTTPException) -> JSONResponse:
        """Render errors as the ``{error}`` body the client expects (DESIGN.md §4)."""
        return JSONResponse(
            status_code=exc.status_code,
            content=shared.ErrorResponse(error=str(exc.detail)).model_dump(),
        )

    def _client() -> PodmanClient:
        return PodmanClient(base_url=config.podman_uri)

    def _get_operation(operation_id: str) -> shared.CreateOperation | None:
        with operations_lock:
            return operations.get(operation_id)

    def _set_operation(operation: shared.CreateOperation) -> None:
        with operations_lock:
            operations[operation.id] = operation

    def _update_operation(
        operation_id: str,
        *,
        status: shared.CreateOperationStatus | None = None,
        stage: str | None = None,
        codespace: shared.Codespace | None = None,
        error: str | None = None,
    ) -> None:
        with operations_lock:
            operation = operations[operation_id]
            operations[operation_id] = operation.model_copy(
                update={
                    k: v
                    for k, v in {
                        "status": status,
                        "stage": stage,
                        "codespace": codespace,
                        "error": error,
                    }.items()
                    if v is not None
                }
            )

    def _set_stage(operation_id: str, cs_id: str, stage: str) -> None:
        logger.info("codespace {} operation {}: {}", cs_id, operation_id, stage)
        _update_operation(operation_id, stage=stage)

    def _build_codespace(
        cs_id: str,
        req: shared.CreateRequest,
        info: podman_ops.ContainerInfo,
        main_keypair: keys.DeployKeypair,
    ) -> shared.Codespace:
        deploy_keys = [
            shared.DeployKeyRef(
                repo=req.repo,
                provider=req.provider,
                public_openssh=main_keypair.public_openssh,
                read_only=False,
            ),
        ]
        return shared.Codespace(
            id=cs_id,
            port=info.port,
            user=shared.DEFAULT_CONTAINER_USER,
            container_id=info.container_id,
            repo=req.repo,
            provider=req.provider,
            git_ssh_host=req.git_ssh_host,
            template=req.template,
            instance=req.instance,
            workspace_dir=shared.workspace_dir_name(req.repo, req.template, req.instance),
            deploy_keys=deploy_keys,
            status="running",
        )

    def _provision_codespace(operation_id: str, cs_id: str, req: shared.CreateRequest) -> None:
        user = shared.DEFAULT_CONTAINER_USER
        workspace_host_dir = _workspace_host_dir(config, req.repo, req.template, req.instance)
        logger.info(
            "creating codespace id={} operation={} repo={} template={} instance={} "
            "user={} image={} workspace_dir={}",
            cs_id,
            operation_id,
            req.repo,
            req.template,
            req.instance,
            user,
            req.image,
            workspace_host_dir,
        )

        try:
            with _client() as client:
                logger.info("codespace {} operation {}: checking workspace", cs_id, operation_id)
                _update_operation(operation_id, status="running", stage="checking workspace")
                existing = podman_ops.find_container_by_instance(
                    client, req.repo, req.template, req.instance
                )
                if existing is not None:
                    existing_id = podman_ops.read_label(existing, shared.LABEL_ID)
                    logger.warning(
                        "codespace {} operation {}: duplicate instance existing_id={}",
                        cs_id,
                        operation_id,
                        existing_id,
                    )
                    raise RuntimeError(
                        f"codespace already exists for repo/template/instance (id={existing_id})"
                    )

                _set_stage(operation_id, cs_id, "generating deploy keys")
                main_keypair = keys.generate_deploy_keypair()

                _set_stage(operation_id, cs_id, "preparing workspace directory")
                podman_ops.ensure_workspace_dir(workspace_host_dir)

                _set_stage(operation_id, cs_id, f"pulling image {req.image}")
                podman_ops.pull_image(client, req.image)

                _set_stage(operation_id, cs_id, "creating container")
                info = podman_ops.create_container(
                    client,
                    cs_id=cs_id,
                    image=req.image,
                    repo=req.repo,
                    provider=req.provider,
                    git_ssh_host=req.git_ssh_host,
                    template=req.template,
                    instance=req.instance,
                    user=user,
                    workspace_host_dir=workspace_host_dir,
                    env=req.env,
                )
                logger.info(
                    "codespace {} operation {}: container created id={} ssh_port={}",
                    cs_id,
                    operation_id,
                    info.container_id,
                    info.port,
                )

                _set_stage(operation_id, cs_id, "injecting credentials")
                podman_ops.inject_credentials(
                    client,
                    cs_id=cs_id,
                    user=user,
                    private_key=main_keypair.private_openssh,
                    login_pubkey=req.login_pubkey,
                    git_ssh_host=req.git_ssh_host,
                )
                _set_stage(operation_id, cs_id, "waiting for ssh")
                podman_ops.wait_for_ssh_ready(info.port)
        except Exception as exc:
            logger.exception("provisioning codespace {} failed; rolling back", cs_id)
            _rollback(config, cs_id)
            _update_operation(operation_id, status="failed", stage="failed", error=str(exc))
            return

        codespace = _build_codespace(cs_id, req, info, main_keypair)
        logger.info("codespace {} ready on port {}", cs_id, info.port)
        _update_operation(
            operation_id,
            status="succeeded",
            stage="ready",
            codespace=codespace,
        )

    @app.post("/codespaces", status_code=202)
    def create_codespace(req: shared.CreateRequest) -> shared.CreateOperation:
        operation_id = secrets.token_hex(6)
        cs_id = secrets.token_hex(3)
        operation = shared.CreateOperation(id=operation_id, status="queued", stage="queued")
        _set_operation(operation)
        Thread(
            target=_provision_codespace,
            args=(operation_id, cs_id, req),
            daemon=True,
        ).start()
        return _get_operation(operation_id) or operation

    @app.get("/operations/{operation_id}")
    def get_operation(operation_id: str) -> shared.CreateOperation:
        operation = _get_operation(operation_id)
        if operation is None:
            raise HTTPException(status_code=404, detail="operation not found")
        return operation

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
            template = podman_ops.read_label(
                container, shared.LABEL_TEMPLATE, shared.DEFAULT_TEMPLATE
            )
            instance = podman_ops.read_label(
                container, shared.LABEL_INSTANCE, shared.DEFAULT_INSTANCE
            )

            podman_ops.remove_container(container)

            workspace_removed = False
            if purge and repo and template and instance:
                podman_ops.purge_workspace(
                    client, _workspace_host_dir(config, repo, template, instance)
                )
                workspace_removed = True

            logger.info("deleted codespace {} (workspace_removed={})", cs_id, workspace_removed)
            return shared.DeleteResponse(ok=True, workspace_removed=workspace_removed)

    @app.post("/codespaces/{cs_id}/clone")
    def clone_codespace_repo(cs_id: str) -> shared.CloneRepoResponse:
        with _client() as client:
            container = podman_ops.get_container(client, cs_id)
            if container is None:
                raise HTTPException(status_code=404, detail="codespace not found")

            repo = podman_ops.read_label(container, shared.LABEL_REPO)
            git_ssh_host = podman_ops.read_label(
                container, shared.LABEL_GIT_SSH_HOST, shared.DEFAULT_GITHUB_SSH_HOST
            )
            user = podman_ops.read_label(
                container, shared.LABEL_USER, shared.DEFAULT_CONTAINER_USER
            )
            if not repo:
                raise HTTPException(status_code=500, detail="codespace repo label is missing")

            try:
                if git_ssh_host == shared.DEFAULT_GITHUB_SSH_HOST:
                    podman_ops.clone_repo(client, cs_id=cs_id, user=user, repo=repo)
                else:
                    podman_ops.clone_repo(
                        client, cs_id=cs_id, user=user, repo=repo, git_ssh_host=git_ssh_host
                    )
            except NotFound as exc:
                if podman_ops.get_container(client, cs_id) is None:
                    logger.info("clone repo for codespace {} aborted: container was deleted", cs_id)
                    raise HTTPException(status_code=404, detail="codespace not found") from exc
                logger.warning("clone repo for codespace {} hit podman not found: {}", cs_id, exc)
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            except Exception as exc:
                logger.exception("clone repo for codespace {} failed", cs_id)
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            return shared.CloneRepoResponse(ok=True)

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
