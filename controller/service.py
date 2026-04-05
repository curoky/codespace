"""Local control-plane orchestration across SSH, Podman and Git providers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock

from loguru import logger
from podman import PodmanClient

from controller import container as containers
from controller import dashboard as dashboard_state
from controller import deployment as deployment_ops
from controller import inventory, provider, ssh, workspace
from controller.config import (
    Config,
    EnvironmentSpec,
    GitWorkspace,
    RepoWorkspace,
    WorkspaceConfig,
)
from controller.models import (
    DashboardResponse,
    DeploymentOperation,
    GitProvider,
    HostStatus,
    Operation,
    OperationStatus,
    RepoGitState,
    deployment_id,
    environment_id,
    git_host,
)
from controller.operations import OperationStore
from controller.runtime.transport import PodmanTransport, SSHRoute


def describe_error(exc: BaseException) -> str:
    """Render an exception and its cause chain."""
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


@dataclass(slots=True)
class _Creation:
    spec: EnvironmentSpec
    token: str | None = None
    client: PodmanClient | None = None
    route: SSHRoute | None = None
    container_created: bool = False
    deploy_key_registered: bool = False


class CodespaceService:
    """Own all mutable state of the single-process local control plane."""

    def __init__(
        self,
        config: Config,
        *,
        transport: PodmanTransport | None = None,
        operations: OperationStore[Operation] | None = None,
        deployment_operations: OperationStore[DeploymentOperation] | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or PodmanTransport(
            {host: options.endpoint() for host, options in config.hosts.items()}
        )
        self.operations: OperationStore[Operation] = operations or OperationStore()
        self.deployment_operations: OperationStore[DeploymentOperation] = (
            deployment_operations or OperationStore()
        )
        self._tokens = config.seed_tokens()
        self._token_lock = Lock()
        ssh.initialize(list(config.hosts))

    def close(self) -> None:
        self.transport.close()

    def set_token(self, provider_name: GitProvider, token: str) -> None:
        with self._token_lock:
            self._tokens[provider_name] = token

    def token_status(self) -> dict[GitProvider, bool]:
        with self._token_lock:
            return {
                "github": "github" in self._tokens,
                "gitlab": "gitlab" in self._tokens,
            }

    def dashboard(self) -> DashboardResponse:
        with ThreadPoolExecutor(max_workers=len(self.config.hosts)) as executor:
            inventories = dict(
                zip(
                    self.config.hosts,
                    executor.map(self._host_inventory, self.config.hosts),
                    strict=True,
                )
            )
        return dashboard_state.build(
            self.config,
            inventories,
            operations=self.operations.list(),
            deployment_operations=self.deployment_operations.list(),
            tokens=self.token_status(),
        )

    def queue_create(self, workspace_id: str, host: str, instance: str) -> Operation:
        ws = self._workspace(workspace_id)
        self._require_host(ws, host)
        if isinstance(ws, RepoWorkspace):
            self._token(ws.provider)
        return self.operations.create(
            Operation(
                id=environment_id(host, workspace_id, instance),
                host=host,
                workspace=workspace_id,
                instance=instance,
                status="queued",
                stage="queued",
            )
        )

    def dismiss_failed_operation(self, workspace_id: str, host: str, instance: str) -> bool:
        ws = self._workspace(workspace_id)
        self._require_host(ws, host)
        return self.operations.dismiss_failed(
            host,
            environment_id(host, workspace_id, instance),
        )

    def create(self, workspace_id: str, host: str, instance: str) -> None:
        ws = self._workspace(workspace_id)
        self._require_host(ws, host)
        creation = _Creation(spec=self.config.environment_spec(workspace_id, host, instance))
        try:
            self._create(creation)
        except Exception as exc:
            logger.exception("failed to create {}", creation.spec.identity)
            rollback_error = self._rollback_create(creation)
            message = describe_error(exc)
            if rollback_error is not None:
                message = f"{message}; rollback stopped: {describe_error(rollback_error)}"
            self.operations.update(
                host,
                creation.spec.identity,
                status="failed",
                stage="failed",
                error=message,
            )
            return
        self.operations.remove(host, creation.spec.identity)

    def _create(self, creation: _Creation) -> None:
        spec = creation.spec
        ws = spec.workspace
        host = spec.host

        self._stage(creation, "checking inventory", status="running")
        if isinstance(ws, RepoWorkspace):
            creation.token = self._token(ws.provider)
        creation.client = self.transport.client(host)
        creation.route = self.transport.ssh_route(host)
        current = inventory.list_inventory(creation.client, host, self.config)
        self._reject_inventory_errors(host, current)
        for environment in current.environments:
            if environment.workspace == spec.workspace_id and environment.instance == spec.instance:
                raise RuntimeError(f"environment {spec.identity!r} already exists")
            if environment.ssh_port == spec.ssh_port:
                raise RuntimeError(
                    f"SSH port collision on host {spec.host!r}: "
                    f"{spec.identity!r} and {environment.id!r} both map to {spec.ssh_port}; "
                    "choose a different instance name"
                )

        host_environment: dict[str, str] = {}
        environment_names = self.config.host_config(host).environment
        if environment_names:
            self._stage(creation, "reading host environment")
            host_environment = ssh.read_host_environment(creation.route, environment_names)

        self._stage(creation, f"pulling image {spec.image}")
        containers.pull_image(creation.client, spec.image, spec.platform)

        self._stage(creation, "preparing workspace")
        paths = ssh.remote_data_paths(creation.route).instance(
            spec.workspace_id,
            spec.instance,
        )
        ssh.prepare_directories(
            creation.route,
            [
                paths.workspace,
                paths.upload,
                paths.cache,
            ],
        )

        self._stage(creation, "creating container")
        creation.container_created = True
        container = containers.create_container(
            creation.client,
            spec,
            paths,
            host_environment,
        )

        deploy_public_key = None
        if isinstance(ws, RepoWorkspace):
            self._stage(creation, "generating deploy key")
            deploy_public_key = workspace.generate_deploy_key(container)

        self._stage(creation, "probing ssh")
        ssh.probe(spec.to_environment(container.id, status="running"), creation.route)

        clone_url: str | None = None
        if isinstance(ws, RepoWorkspace):
            if deploy_public_key is None:
                raise RuntimeError("deploy key missing for repo workspace")
            if creation.token is None:
                raise RuntimeError("provider token missing for repo workspace")
            self._stage(creation, "registering deploy key")
            provider.register(
                ws.provider,
                creation.token,
                ws.repo,
                spec.identity,
                deploy_public_key,
            )
            creation.deploy_key_registered = True
            self._stage(creation, "cloning repository")
            clone_url = f"git@{git_host(ws.provider)}:{ws.repo}.git"
        elif isinstance(ws, GitWorkspace):
            self._stage(creation, "cloning repository")
            clone_url = ws.git_url
        else:
            self._stage(creation, "preparing open path")
        workspace.bootstrap(
            container,
            clone_url=clone_url,
            clone_path=spec.clone_path,
            open_path=spec.open_path,
        )

        self._stage(creation, "writing ssh config")
        refreshed = inventory.list_inventory(creation.client, host, self.config)
        self._reject_inventory_errors(host, refreshed)
        ssh.write_host(host, refreshed.environments, creation.route)

    def delete(
        self, workspace_id: str, host: str, instance: str, *, purge: bool, force: bool = False
    ) -> RepoGitState:
        """Inspect when unforced; otherwise delete the environment."""
        ws = self._workspace(workspace_id)
        self._require_host(ws, host)
        spec = self.config.environment_spec(workspace_id, host, instance)
        token = self._token(ws.provider) if isinstance(ws, RepoWorkspace) else None
        client = self.transport.client(host)
        route = self.transport.ssh_route(host)
        current = inventory.list_inventory(client, host, self.config)
        self._reject_inventory_errors(host, current)
        environment = next(
            (
                item
                for item in current.environments
                if item.workspace == workspace_id and item.instance == instance
            ),
            None,
        )
        if environment is None:
            raise RuntimeError(f"environment {spec.identity!r} not found")
        container = inventory.find_container(client, spec, self.config)
        if container is None:
            raise RuntimeError(f"environment {spec.identity!r} not found")

        if not force:
            if isinstance(ws, RepoWorkspace | GitWorkspace):
                if environment.status != "running":
                    status = environment.status or "unknown"
                    raise RuntimeError(
                        f"container {spec.identity!r} is {status}; "
                        "repository state cannot be inspected while it is not running"
                    )
                return workspace.checkout_git_state(container, spec.clone_path)
            return RepoGitState()

        if isinstance(ws, RepoWorkspace) and token is not None:
            provider.revoke(ws.provider, token, ws.repo, spec.identity)
        if purge:
            paths = ssh.remote_data_paths(route).instance(workspace_id, instance)
            containers.purge_workspace(
                client,
                container,
                environment,
                paths,
            )
        containers.remove_container(container)

        refreshed = inventory.list_inventory(client, host, self.config)
        self._reject_inventory_errors(host, refreshed)
        ssh.write_host(host, refreshed.environments, route)
        return RepoGitState()

    def logs(self, workspace_id: str, host: str, instance: str) -> str:
        ws = self._workspace(workspace_id)
        self._require_host(ws, host)
        spec = self.config.environment_spec(workspace_id, host, instance)
        container = inventory.find_container(self.transport.client(host), spec, self.config)
        if container is None:
            raise RuntimeError(f"environment {spec.identity!r} not found")
        return containers.container_logs(container)

    def queue_deploy(self, deployment: str, host: str) -> DeploymentOperation:
        self._require_deployment_host(deployment, host)
        return self.deployment_operations.create(
            DeploymentOperation(
                id=deployment_id(deployment),
                host=host,
                deployment=deployment,
                status="queued",
                stage="queued",
            )
        )

    def dismiss_failed_deployment_operation(self, deployment: str, host: str) -> bool:
        self._require_deployment_host(deployment, host)
        return self.deployment_operations.dismiss_failed(host, deployment_id(deployment))

    def deploy(self, deployment: str, host: str) -> None:
        spec = self.config.deployment_spec(deployment, host)
        try:
            deployment_ops.reconcile(
                self.transport.client(host),
                self.transport.ssh_route(host),
                spec,
                stage=lambda stage: self.deployment_operations.update(
                    spec.host,
                    spec.identity,
                    status="running",
                    stage=stage,
                ),
            )
        except Exception as exc:
            logger.exception("failed to deploy {}", spec.identity)
            self.deployment_operations.update(
                host,
                spec.identity,
                status="failed",
                stage="failed",
                error=describe_error(exc),
            )
            return
        self.deployment_operations.remove(host, spec.identity)

    def clean_deployment(self, deployment: str, host: str, *, purge: bool = False) -> bool:
        self._require_deployment_host(deployment, host)
        spec = self.config.deployment_spec(deployment, host)
        return deployment_ops.teardown(
            self.transport.client(host),
            self.transport.ssh_route(host),
            spec,
            self.config,
            purge=purge,
            stage=lambda _stage: None,
        )

    def deployment_logs(self, deployment: str, host: str) -> str:
        self._require_deployment_host(deployment, host)
        container = inventory.find_deployment_container(
            self.transport.client(host),
            deployment,
            host,
            self.config,
        )
        if container is None:
            raise RuntimeError(f"deployment {deployment!r} not found on host {host!r}")
        return containers.container_logs(container)

    def _require_deployment_host(self, deployment: str, host: str) -> None:
        if deployment not in self.config.deployments:
            raise KeyError(f"unknown deployment: {deployment}")
        allowed = self.config.deployment_hosts(deployment)
        if host not in allowed:
            raise KeyError(
                f"host {host!r} does not declare deployment {deployment!r}; allowed: {allowed}"
            )

    def _host_inventory(self, host: str) -> dashboard_state.HostInventory:
        try:
            client = self.transport.client(host)
            route = self.transport.ssh_route(host)
            current = inventory.list_inventory(client, host, self.config)
            if not current.errors:
                ssh.write_host(host, current.environments, route)
            deployments = inventory.list_deployments(client, host, self.config)
            errors = current.errors + deployments.errors
            return dashboard_state.HostInventory(
                status=HostStatus(
                    id=host,
                    status="online",
                    environment_count=len(current.environments),
                    inventory_errors=errors,
                    error="; ".join(errors) if errors else None,
                ),
                environments=current.environments,
                deployments=deployments,
            )
        except Exception as exc:
            return dashboard_state.HostInventory(
                status=HostStatus(id=host, status="offline", error=describe_error(exc)),
                environments=[],
                deployments=None,
            )

    def _rollback_create(self, creation: _Creation) -> Exception | None:
        spec = creation.spec
        ws = spec.workspace
        if creation.deploy_key_registered:
            if creation.token is None:
                return RuntimeError("provider token is unavailable; container retained")
            if not isinstance(ws, RepoWorkspace):
                return RuntimeError("deploy key registered for a non-repo workspace")
            try:
                provider.revoke(ws.provider, creation.token, ws.repo, spec.identity)
            except Exception as exc:
                if creation.client is not None and creation.container_created:
                    try:
                        container = inventory.find_container(
                            creation.client,
                            spec,
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
            container = inventory.find_container(creation.client, spec, self.config)
            if container is not None:
                containers.remove_container(container)
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
            creation.spec.host,
            creation.spec.identity,
            status=status,
            stage=stage,
        )

    def _workspace(self, workspace_id: str) -> WorkspaceConfig:
        try:
            return self.config.workspaces.items[workspace_id]
        except KeyError as exc:
            raise KeyError(f"unknown workspace: {workspace_id}") from exc

    @staticmethod
    def _require_host(ws: WorkspaceConfig, host: str) -> None:
        if all(entry.name != host for entry in ws.host):
            allowed = sorted(entry.name for entry in ws.host)
            raise KeyError(
                f"host {host!r} is not configured for this workspace; allowed: {allowed}"
            )

    def _token(self, provider_name: GitProvider) -> str:
        with self._token_lock:
            token = self._tokens.get(provider_name)
        if token is None:
            raise RuntimeError(f"{provider_name} token is not set")
        return token

    @staticmethod
    def _reject_inventory_errors(host: str, current: inventory.Inventory) -> None:
        if current.errors:
            raise RuntimeError(
                f"host {host!r} has invalid managed inventory: " + "; ".join(current.errors)
            )
