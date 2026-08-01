"""Local control-plane orchestration across SSH, Podman and Git providers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock

from loguru import logger
from podman import PodmanClient

from codespace.client import provider, runtime, ssh
from codespace.client.config import Config, ProjectConfig
from codespace.client.models import (
    DashboardEnvironment,
    DashboardResponse,
    Environment,
    GitProvider,
    HostStatus,
    ImagePlatform,
    Operation,
    OperationStatus,
    ProjectSummary,
    environment_id,
    ssh_port,
    workspace_path,
)
from codespace.client.operations import OperationStore
from codespace.client.transport import PodmanTransport


def describe_error(exc: BaseException) -> str:
    """Render an exception with its cause chain.

    Some clients (notably podman-py's ``APIError``) format only a bare URL and a
    generic phrase like ``GET operation failed`` while stashing the real cause
    (e.g. ``TimeoutError: timed out``) on ``__cause__``. Walk the chain so the
    surfaced message keeps the actual failure instead of silently dropping it.
    """
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip()
        rendered = f"{type(current).__name__}: {text}" if text else type(current).__name__
        if rendered not in parts:
            parts.append(rendered)
        current = current.__cause__ or current.__context__
    return " <- ".join(parts)


@dataclass(frozen=True, slots=True)
class _HostInventory:
    """Dashboard inventory result for one host."""

    status: HostStatus
    environments: list[Environment]


@dataclass(slots=True)
class _Creation:
    """Inputs and rollback state for one create operation."""

    project_id: str
    instance: str
    project: ProjectConfig
    image: str
    platform: ImagePlatform | None
    identity: str
    token: str | None = None
    client: PodmanClient | None = None
    container_created: bool = False
    deploy_key_registered: bool = False


class CodespaceService:
    """Own all mutable state of the single-process local control plane."""

    def __init__(
        self,
        config: Config,
        *,
        transport: PodmanTransport | None = None,
        operations: OperationStore | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or PodmanTransport(config.podman_sockets())
        self.operations = operations or OperationStore()
        self._tokens: dict[GitProvider, str] = {}
        self._token_lock = Lock()
        self._tokens.update(config.seed_tokens())
        ssh.initialize(config.hosts)

    def close(self) -> None:
        """Release all host tunnels."""
        self.transport.close()

    def set_token(self, provider_name: GitProvider, token: str) -> None:
        """Store one provider token in process memory only."""
        with self._token_lock:
            self._tokens[provider_name] = token

    def token_status(self) -> dict[GitProvider, bool]:
        """Return token presence without exposing token values."""
        with self._token_lock:
            return {
                "github": "github" in self._tokens,
                "gitlab": "gitlab" in self._tokens,
            }

    def dashboard(self) -> DashboardResponse:
        """Query all hosts concurrently and project the complete browser state."""
        results = self._all_host_inventories()
        hosts: list[HostStatus] = []
        environments: list[Environment] = []
        for host in self.config.hosts:
            result = results[host]
            hosts.append(result.status)
            environments.extend(result.environments)

        return DashboardResponse(
            hosts=hosts,
            projects=[
                ProjectSummary(
                    id=project_id,
                    host=project.host,
                    provider=project.provider,
                    repo=project.repo,
                    image=self.config.project_image(project_id),
                    platform=project.platform,
                    description=project.description,
                )
                for project_id, project in self.config.projects.items()
            ],
            environments=[
                DashboardEnvironment.from_environment(environment)
                for environment in sorted(
                    environments,
                    key=lambda item: (item.project, item.instance),
                )
            ],
            operations=self.operations.list(),
            tokens=self.token_status(),
        )

    def queue_create(self, project_id: str, instance: str) -> Operation:
        """Validate synchronous prerequisites and create a queued operation."""
        project = self._project(project_id)
        self._token(project.provider)
        return self.operations.create(project.host, project_id, instance)

    def create(self, project_id: str, instance: str) -> None:
        """Run one complete local creation operation with fail-closed rollback."""
        project = self._project(project_id)
        creation = _Creation(
            project_id=project_id,
            instance=instance,
            project=project,
            image=self.config.project_image(project_id),
            platform=project.platform,
            identity=environment_id(project.host, project_id, instance),
        )
        try:
            self._create(creation)
        except Exception as exc:
            logger.exception("failed to create {}", creation.identity)
            rollback_error = self._rollback_create(creation)
            message = describe_error(exc)
            if rollback_error is not None:
                message = f"{message}; rollback stopped: {describe_error(rollback_error)}"
            self.operations.update(
                project_id,
                instance,
                status="failed",
                stage="failed",
                error=message,
            )
            return

        self.operations.remove(project_id, instance)

    def _create(self, creation: _Creation) -> None:
        project = creation.project

        self._stage(creation, "checking inventory", status="running")
        creation.token = self._token(project.provider)
        creation.client = self.transport.client(project.host)
        inventory = runtime.list_inventory(creation.client, project.host, self.config)
        self._reject_inventory_errors(project.host, inventory)
        self._reject_duplicate_and_collision(
            inventory.environments,
            creation.project_id,
            creation.instance,
        )

        self._stage(creation, "preparing login key")
        login_public_key = ssh.ensure_login_key()

        self._stage(creation, "generating deploy key")
        deploy_keypair = runtime.generate_deploy_keypair()

        self._stage(creation, f"pulling image {creation.image}")
        runtime.pull_image(creation.client, creation.image, creation.platform)

        self._stage(creation, "preparing workspace")
        workspace_root = ssh.remote_workspace_root(project.host)
        ssh.prepare_workspace(
            project.host,
            workspace_path(workspace_root, creation.project_id, creation.instance),
        )

        self._stage(creation, "creating container")
        creation.container_created = True
        container = runtime.create_container(
            creation.client,
            host=project.host,
            project=creation.project_id,
            instance=creation.instance,
            repo=project.repo,
            provider=project.provider,
            image=creation.image,
            platform=creation.platform,
            workspace_root=workspace_root,
        )

        self._stage(creation, "injecting credentials")
        runtime.inject_credentials(
            container,
            login_public_key=login_public_key,
            deploy_private_key=deploy_keypair.private_key,
            provider=project.provider,
        )

        environment = Environment(
            id=creation.identity,
            host=project.host,
            project=creation.project_id,
            instance=creation.instance,
            repo=project.repo,
            provider=project.provider,
            image=creation.image,
            platform=creation.platform or "native",
            ssh_port=ssh_port(creation.identity),
            container_id=container.id,
            status="running",
        )
        self._stage(creation, "probing ssh")
        ssh.probe(environment)

        self._stage(creation, "registering deploy key")
        provider.register(
            project.provider,
            creation.token,
            project.repo,
            creation.identity,
            deploy_keypair.public_key,
        )
        creation.deploy_key_registered = True

        self._stage(creation, "cloning repository")
        runtime.clone_repo(container, project.repo, project.provider)

        self._stage(creation, "writing ssh config")
        refreshed = runtime.list_inventory(creation.client, project.host, self.config)
        self._reject_inventory_errors(project.host, refreshed)
        ssh.write_host(project.host, refreshed.environments)

    def delete(self, project_id: str, instance: str, *, purge: bool) -> None:
        """Revoke provider state before deleting a container or workspace."""
        project = self._project(project_id)
        token = self._token(project.provider)
        identity = environment_id(project.host, project_id, instance)
        client = self.transport.client(project.host)
        inventory = runtime.list_inventory(client, project.host, self.config)
        self._reject_inventory_errors(project.host, inventory)
        environment = next(
            (
                item
                for item in inventory.environments
                if item.project == project_id and item.instance == instance
            ),
            None,
        )
        if environment is None:
            raise RuntimeError(f"environment {identity!r} not found")
        container = runtime.find_container(
            client,
            project.host,
            project_id,
            instance,
            self.config,
        )
        if container is None:
            raise RuntimeError(f"environment {identity!r} not found")

        provider.revoke(
            project.provider,
            token,
            project.repo,
            identity,
        )
        if purge:
            workspace_root = ssh.remote_workspace_root(project.host)
            runtime.purge_workspace(
                client,
                container,
                environment.image,
                None if environment.platform == "native" else environment.platform,
                workspace_root,
                project_id,
                instance,
            )
        runtime.remove_container(container)

        refreshed = runtime.list_inventory(client, project.host, self.config)
        self._reject_inventory_errors(project.host, refreshed)
        ssh.write_host(project.host, refreshed.environments)

    def _all_host_inventories(self) -> dict[str, _HostInventory]:
        with ThreadPoolExecutor(max_workers=len(self.config.hosts)) as executor:
            inventories = executor.map(self._host_inventory, self.config.hosts)
            return dict(zip(self.config.hosts, inventories, strict=True))

    def _host_inventory(self, host: str) -> _HostInventory:
        try:
            client = self.transport.client(host)
            inventory = runtime.list_inventory(client, host, self.config)
            if not inventory.errors:
                ssh.write_host(host, inventory.environments)
            return _HostInventory(
                status=HostStatus(
                    id=host,
                    status="online",
                    environment_count=len(inventory.environments),
                    inventory_errors=inventory.errors,
                    error="; ".join(inventory.errors) if inventory.errors else None,
                ),
                environments=inventory.environments,
            )
        except Exception as exc:
            return _HostInventory(
                status=HostStatus(id=host, status="offline", error=describe_error(exc)),
                environments=[],
            )

    def _reject_duplicate_and_collision(
        self,
        environments: list[Environment],
        project_id: str,
        instance: str,
    ) -> None:
        project = self.config.projects[project_id]
        identity = environment_id(project.host, project_id, instance)
        port = ssh_port(identity)
        for environment in environments:
            if environment.project == project_id and environment.instance == instance:
                raise RuntimeError(f"environment {identity!r} already exists")
            if environment.ssh_port == port:
                raise RuntimeError(
                    f"SSH port collision on host {project.host!r}: "
                    f"{identity!r} and {environment.id!r} both map to {port}; "
                    "choose a different instance name"
                )

    def _rollback_create(self, creation: _Creation) -> Exception | None:
        if creation.deploy_key_registered:
            if creation.token is None:
                return RuntimeError("provider token is unavailable; container retained")
            try:
                provider.revoke(
                    creation.project.provider,
                    creation.token,
                    creation.project.repo,
                    creation.identity,
                )
            except Exception as exc:
                if creation.client is not None and creation.container_created:
                    try:
                        container = runtime.find_container(
                            creation.client,
                            creation.project.host,
                            creation.project_id,
                            creation.instance,
                            self.config,
                        )
                        if container is not None:
                            container.stop(timeout=10)
                    except Exception as stop_exc:
                        return RuntimeError(f"{exc}; failed to stop retained container: {stop_exc}")
                return exc
        if not creation.container_created or creation.client is None:
            return None
        try:
            container = runtime.find_container(
                creation.client,
                creation.project.host,
                creation.project_id,
                creation.instance,
                self.config,
            )
            if container is not None:
                runtime.remove_container(container)
        except Exception as exc:
            return exc
        return None

    def _stage(
        self,
        creation: _Creation,
        stage: str,
        *,
        status: OperationStatus | None = None,
    ) -> None:
        self.operations.update(
            creation.project_id,
            creation.instance,
            status=status,
            stage=stage,
        )

    def _project(self, project_id: str) -> ProjectConfig:
        try:
            return self.config.projects[project_id]
        except KeyError as exc:
            raise KeyError(f"unknown project: {project_id}") from exc

    def _token(self, provider_name: GitProvider) -> str:
        token = self._optional_token(provider_name)
        if token is None:
            raise RuntimeError(f"{provider_name} token is not set")
        return token

    def _optional_token(self, provider_name: GitProvider) -> str | None:
        with self._token_lock:
            return self._tokens.get(provider_name)

    @staticmethod
    def _reject_inventory_errors(host: str, inventory: runtime.Inventory) -> None:
        if inventory.errors:
            raise RuntimeError(
                f"host {host!r} has invalid managed inventory: " + "; ".join(inventory.errors)
            )
