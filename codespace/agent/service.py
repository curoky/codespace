"""Codespace provisioning orchestration for the agent.

``CodespaceProvisioner`` runs the multi-stage create flow (dedup, keygen,
workspace, image pull, container, credential injection, ssh probe) and records
progress on the shared :class:`OperationStore`. Pulling it out of the FastAPI
closure keeps the orchestration independently testable. See DESIGN.md
"Agent 创建流程".
"""

from collections.abc import Callable
from threading import Lock

from loguru import logger
from podman import PodmanClient

from codespace import shared
from codespace.agent import containers, credentials, keys
from codespace.agent.config import AgentConfig, workspace_host_dir
from codespace.agent.containers import ContainerInfo
from codespace.agent.operations import OperationStore


class CodespaceProvisioner:
    """Run and roll back asynchronous codespace create operations."""

    def __init__(
        self,
        config: AgentConfig,
        operations: OperationStore,
        client_factory: Callable[[], PodmanClient],
    ) -> None:
        self._config = config
        self._operations = operations
        self._client_factory = client_factory
        self._creating_instances: set[tuple[str, str, str]] = set()
        self._creating_instances_lock = Lock()

    def provision(self, operation_id: str, cs_id: str, req: shared.CreateRequest) -> None:
        """Provision a codespace end to end, rolling back on any failure."""
        user = shared.DEFAULT_CONTAINER_USER
        instance_key = (req.repo, req.template, req.instance)
        workspace_dir = workspace_host_dir(self._config, req.repo, req.template, req.instance)
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
            workspace_dir,
        )

        reserved_instance = False
        try:
            reserved_instance = self._reserve_instance(instance_key)
            with self._client_factory() as client:
                self._set_stage(operation_id, cs_id, "checking workspace")
                self._operations.update(operation_id, status="running", stage="checking workspace")
                self._reject_if_duplicate(client, operation_id, cs_id, req)

                self._set_stage(operation_id, cs_id, "generating deploy keys")
                main_keypair = keys.generate_deploy_keypair()

                self._set_stage(operation_id, cs_id, "preparing workspace directory")
                containers.ensure_workspace_dir(workspace_dir)

                self._set_stage(operation_id, cs_id, f"pulling image {req.image}")
                containers.pull_image(client, req.image)

                self._set_stage(operation_id, cs_id, "creating container")
                info = containers.create_container(
                    client,
                    cs_id=cs_id,
                    image=req.image,
                    repo=req.repo,
                    provider=req.provider,
                    template=req.template,
                    instance=req.instance,
                    user=user,
                    workspace_host_dir=workspace_dir,
                )
                logger.info(
                    "codespace {} operation {}: container created id={} ssh_port={}",
                    cs_id,
                    operation_id,
                    info.container_id,
                    info.port,
                )

                self._set_stage(operation_id, cs_id, "injecting credentials")
                credentials.inject_credentials(
                    client,
                    cs_id=cs_id,
                    user=user,
                    private_key=main_keypair.private_openssh,
                    login_pubkey=req.login_pubkey,
                    provider=req.provider,
                )
                self._set_stage(operation_id, cs_id, "waiting for ssh")
                containers.wait_for_ssh_ready(info.port)
        except Exception as exc:
            logger.exception("provisioning codespace {} failed; rolling back", cs_id)
            self._rollback(cs_id)
            self._operations.update(operation_id, status="failed", stage="failed", error=str(exc))
            return
        finally:
            if reserved_instance:
                with self._creating_instances_lock:
                    self._creating_instances.discard(instance_key)

        codespace = self._build_codespace(cs_id, req, info, main_keypair)
        logger.info("codespace {} ready on port {}", cs_id, info.port)
        self._operations.update(
            operation_id,
            status="succeeded",
            stage="ready",
            codespace=codespace,
        )

    def _reserve_instance(self, instance_key: tuple[str, str, str]) -> bool:
        """Claim an in-flight instance slot, rejecting concurrent duplicate creates."""
        with self._creating_instances_lock:
            if instance_key in self._creating_instances:
                raise RuntimeError(
                    "codespace creation is already running for repo/template/instance"
                )
            self._creating_instances.add(instance_key)
        return True

    def _reject_if_duplicate(
        self, client: PodmanClient, operation_id: str, cs_id: str, req: shared.CreateRequest
    ) -> None:
        """Fail the operation if a container already exists for the instance tuple."""
        existing = containers.find_container_by_instance(
            client, req.repo, req.template, req.instance
        )
        if existing is None:
            return
        existing_id = containers.read_label(existing, shared.LABEL_ID)
        existing_status = containers.container_status(existing) or "unknown"
        existing_name = getattr(existing, "name", None)
        logger.warning(
            "codespace {} operation {}: duplicate instance existing_id={} "
            "existing_name={} existing_status={}",
            cs_id,
            operation_id,
            existing_id,
            existing_name,
            existing_status,
        )
        raise RuntimeError(
            "codespace already exists for repo/template/instance "
            f"(id={existing_id}, name={existing_name}, status={existing_status})"
        )

    def _build_codespace(
        self,
        cs_id: str,
        req: shared.CreateRequest,
        info: ContainerInfo,
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
            template=req.template,
            instance=req.instance,
            workspace_dir=shared.workspace_dir_name(req.repo, req.template, req.instance),
            deploy_keys=deploy_keys,
            status="running",
        )

    def _rollback(self, cs_id: str) -> None:
        """Best-effort container cleanup after a failed create.

        No provider key exists yet at this point (the client registers it only
        after a successful create), so rollback only needs to remove the
        container.
        """
        try:
            with self._client_factory() as client:
                container = containers.get_container(client, cs_id)
                if container is not None:
                    containers.remove_container(container)
        except Exception as exc:
            logger.error("rollback: failed to remove container for {}: {}", cs_id, exc)

    def _set_stage(self, operation_id: str, cs_id: str, stage: str) -> None:
        logger.info("codespace {} operation {}: {}", cs_id, operation_id, stage)
        self._operations.update(operation_id, stage=stage)
