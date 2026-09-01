"""Local control-plane orchestration across SSH, Podman and Git providers."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock

from loguru import logger
from podman import PodmanClient

from controller import agent, inventory, provider, ssh
from controller import container as containers
from controller import dashboard as dashboard_state
from controller import deployment as deployment_ops
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
)
from controller.operations import OperationStore
from controller.runtime.transport import PodmanTransport, SSHRoute

_AGENT_START_TIMEOUT = 60.0
_AGENT_READY_TIMEOUT = 15 * 60.0


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
        self._run_operation(
            self.operations,
            host,
            creation.spec.identity,
            lambda: self._create(creation),
            on_failure=lambda: self._rollback_message(creation),
        )

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
                *(mount[0] for mount in paths.home_cache_mounts),
                paths.control,
            ],
        )
        ssh.reset_control_state(creation.route, paths.control)

        self._stage(creation, "creating container")
        creation.container_created = True
        container = containers.create_container(
            creation.client,
            spec,
            paths,
            host_environment,
        )

        self._stage(creation, "waiting for workspace agent")
        agent_client = agent.WorkspaceAgentClient(
            self.transport.forward_socket(host, f"{paths.control}/agent.sock")
        )
        if isinstance(ws, RepoWorkspace):
            status = agent_client.wait_for(
                {"awaiting-provider"},
                timeout=_AGENT_START_TIMEOUT,
            )
            if status.public_key is None:
                raise RuntimeError("deploy key missing for repo workspace")
            if creation.token is None:
                raise RuntimeError("provider token missing for repo workspace")
            self._stage(creation, "registering deploy key")
            provider.register(
                ws.provider,
                creation.token,
                ws.repo,
                spec.identity,
                status.public_key,
            )
            creation.deploy_key_registered = True
            self._stage(creation, "authorizing repository bootstrap")
            ssh.signal_provider_ready(creation.route, paths.control)
        if isinstance(ws, RepoWorkspace | GitWorkspace):
            self._stage(creation, "cloning repository")
        else:
            self._stage(creation, "preparing open path")
        agent_client.wait_for(
            {"ready"},
            timeout=_AGENT_READY_TIMEOUT,
        )

        self._stage(creation, "probing ssh")
        ssh.probe(spec.to_environment(container.id, status="running"), creation.route)

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
                paths = ssh.remote_data_paths(route).instance(workspace_id, instance)
                agent_client = agent.WorkspaceAgentClient(
                    self.transport.forward_socket(host, f"{paths.control}/agent.sock")
                )
                return agent_client.git_state()
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
        self._run_operation(
            self.deployment_operations,
            host,
            spec.identity,
            lambda: deployment_ops.reconcile(
                self.transport.client(host),
                self.transport.ssh_route(host),
                spec,
                stage=lambda stage: self.deployment_operations.update(
                    spec.host,
                    spec.identity,
                    status="running",
                    stage=stage,
                ),
            ),
        )

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

    def _run_operation(
        self,
        store: OperationStore[Operation] | OperationStore[DeploymentOperation],
        host: str,
        resource_id: str,
        work: Callable[[], object],
        *,
        on_failure: Callable[[], str | None] = lambda: None,
    ) -> None:
        """Run one background operation, recording failure or clearing on success.

        ``work`` performs the operation; on any exception it is logged, the error
        (optionally augmented by ``on_failure`` for cleanup follow-up) is stored on
        the operation, and the operation is left in ``failed`` state. On success the
        operation is removed from the store.
        """
        try:
            work()
        except Exception as exc:
            logger.exception("failed operation {} on host {}", resource_id, host)
            message = describe_error(exc)
            if (follow_up := on_failure()) is not None:
                message = f"{message}; {follow_up}"
            store.update(host, resource_id, status="failed", stage="failed", error=message)
            return
        store.remove(host, resource_id)

    def _rollback_message(self, creation: _Creation) -> str | None:
        rollback_error = self._rollback_create(creation)
        if rollback_error is None:
            return None
        return f"rollback stopped: {describe_error(rollback_error)}"

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
