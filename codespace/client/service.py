"""Local control-plane orchestration across SSH, Podman and Git providers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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
    OperationStatus,
    ProjectSummary,
    deploy_key_title,
    environment_id,
    ssh_port,
)
from codespace.client.operations import OperationStore
from codespace.client.transport import PodmanTransport


@dataclass(frozen=True, slots=True)
class HostInventory:
    """Dashboard inventory result for one host."""

    status: HostStatus
    environments: list[Environment]


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

    def queue_create(self, project_id: str, instance: str) -> str:
        """Validate synchronous prerequisites and create a queued operation."""
        project = self._project(project_id)
        self._token(project.provider)
        operation = self.operations.create(project.host, project_id, instance)
        return operation.id

    def create(self, project_id: str, instance: str) -> None:
        """Run one complete local creation operation with fail-closed rollback."""
        project = self._project(project_id)
        image = self.config.project_image(project_id)
        identity = environment_id(project.host, project_id, instance)
        registered = False
        container_created = False
        client: PodmanClient | None = None
        try:
            self._stage(project_id, instance, "checking inventory", status="running")
            token = self._token(project.provider)
            client = self.transport.client(project.host)
            inventory = runtime.list_inventory(client, project.host, self.config)
            self._reject_inventory_errors(project.host, inventory)
            self._reject_duplicate_and_collision(inventory.environments, project_id, instance)

            self._stage(project_id, instance, "preparing login key")
            login_public_key = ssh.ensure_login_key()

            self._stage(project_id, instance, "generating deploy key")
            deploy_keypair = runtime.generate_deploy_keypair()

            self._stage(project_id, instance, f"pulling image {image}")
            runtime.pull_image(client, image)

            self._stage(project_id, instance, "preparing workspace")
            workspace_root = ssh.remote_workspace_root(project.host)
            runtime.prepare_workspace(client, image, workspace_root, project_id, instance)

            self._stage(project_id, instance, "creating container")
            container_created = True
            container = runtime.create_container(
                client,
                host=project.host,
                project=project_id,
                instance=instance,
                repo=project.repo,
                provider=project.provider,
                image=image,
                workspace_root=workspace_root,
            )

            self._stage(project_id, instance, "injecting credentials")
            runtime.inject_credentials(
                container,
                login_public_key=login_public_key,
                deploy_private_key=deploy_keypair.private_key,
                provider=project.provider,
            )

            environment = Environment(
                id=identity,
                host=project.host,
                project=project_id,
                instance=instance,
                repo=project.repo,
                provider=project.provider,
                image=image,
                ssh_port=ssh_port(identity),
                container_id=container.id,
                status="running",
            )
            self._stage(project_id, instance, "probing ssh")
            ssh.probe(environment)

            self._stage(project_id, instance, "registering deploy key")
            provider.register(
                project.provider,
                token,
                project.repo,
                deploy_key_title(identity),
                deploy_keypair.public_key,
            )
            registered = True

            self._stage(project_id, instance, "cloning repository")
            runtime.clone_repo(container, project.repo, project.provider)

            self._stage(project_id, instance, "writing ssh config")
            refreshed = runtime.list_inventory(client, project.host, self.config)
            self._reject_inventory_errors(project.host, refreshed)
            ssh.write_host(project.host, refreshed.environments)
        except Exception as exc:
            logger.exception("failed to create {}", identity)
            rollback_error = self._rollback_create(
                client=client,
                host=project.host,
                project=project_id,
                instance=instance,
                provider_name=project.provider,
                token=self._optional_token(project.provider),
                repo=project.repo,
                identity=identity,
                registered=registered,
                container_created=container_created,
            )
            message = str(exc)
            if rollback_error is not None:
                message = f"{message}; rollback stopped: {rollback_error}"
            self.operations.update(
                project_id,
                instance,
                status="failed",
                stage="failed",
                error=message,
            )
            return

        self.operations.remove(project_id, instance)

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
            deploy_key_title(identity),
        )
        if purge:
            workspace_root = ssh.remote_workspace_root(project.host)
            runtime.purge_workspace(
                client,
                container,
                environment.image,
                workspace_root,
                project_id,
                instance,
            )
        runtime.remove_container(container)

        refreshed = runtime.list_inventory(client, project.host, self.config)
        self._reject_inventory_errors(project.host, refreshed)
        ssh.write_host(project.host, refreshed.environments)

    def _all_host_inventories(self) -> dict[str, HostInventory]:
        results: dict[str, HostInventory] = {}
        with ThreadPoolExecutor(max_workers=len(self.config.hosts)) as executor:
            futures = {
                executor.submit(self._host_inventory, host): host for host in self.config.hosts
            }
            for future in as_completed(futures):
                host = futures[future]
                results[host] = future.result()
        return results

    def _host_inventory(self, host: str) -> HostInventory:
        try:
            client = self.transport.client(host)
            inventory = runtime.list_inventory(client, host, self.config)
            if not inventory.errors:
                ssh.write_host(host, inventory.environments)
            return HostInventory(
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
            return HostInventory(
                status=HostStatus(id=host, status="offline", error=str(exc)),
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

    def _rollback_create(
        self,
        *,
        client: PodmanClient | None,
        host: str,
        project: str,
        instance: str,
        provider_name: GitProvider,
        token: str | None,
        repo: str,
        identity: str,
        registered: bool,
        container_created: bool,
    ) -> Exception | None:
        if registered:
            if token is None:
                return RuntimeError("provider token is unavailable; container retained")
            try:
                provider.revoke(
                    provider_name,
                    token,
                    repo,
                    deploy_key_title(identity),
                )
            except Exception as exc:
                if client is not None and container_created:
                    try:
                        container = runtime.find_container(
                            client,
                            host,
                            project,
                            instance,
                            self.config,
                        )
                        if container is not None:
                            container.stop(timeout=10)
                    except Exception as stop_exc:
                        return RuntimeError(f"{exc}; failed to stop retained container: {stop_exc}")
                return exc
        if not container_created or client is None:
            return None
        try:
            container = runtime.find_container(
                client,
                host,
                project,
                instance,
                self.config,
            )
            if container is not None:
                runtime.remove_container(container)
        except Exception as exc:
            return exc
        return None

    def _stage(
        self,
        project: str,
        instance: str,
        stage: str,
        *,
        status: OperationStatus | None = None,
    ) -> None:
        self.operations.update(
            project,
            instance,
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
