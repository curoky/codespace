"""Local control-plane orchestration across SSH, Podman and Git providers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock

from loguru import logger
from podman import PodmanClient

from controller import container as containers
from controller import dashboard as dashboard_state
from controller import inventory, provider, ssh, workspace
from controller.config import Config, ProjectConfig
from controller.models import (
    DashboardResponse,
    Environment,
    EnvironmentSpec,
    GitProvider,
    HostStatus,
    Operation,
    OperationStatus,
    RepoGitState,
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
        operations: OperationStore | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or PodmanTransport(
            {host: hc.endpoint() for host, hc in config.hosts.items()}
        )
        self.operations = operations or OperationStore()
        self._tokens: dict[GitProvider, str] = {}
        self._token_lock = Lock()
        self._tokens.update(config.seed_tokens())
        ssh.initialize(list(self.config.hosts))

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
        return dashboard_state.build(
            self.config,
            self._all_host_inventories(),
            operations=self.operations.list(),
            tokens=self.token_status(),
        )

    def queue_create(self, project_id: str, host: str, instance: str) -> Operation:
        project = self._project(project_id)
        self._require_host(project, host)
        if project.type == "repo":
            self._token(self._require_provider(project))
        return self.operations.create(host, project_id, instance)

    def dismiss_failed_operation(self, project_id: str, host: str, instance: str) -> bool:
        project = self._project(project_id)
        self._require_host(project, host)
        return self.operations.dismiss_failed(host, project_id, instance)

    def create(self, project_id: str, host: str, instance: str) -> None:
        project = self._project(project_id)
        self._require_host(project, host)
        creation = _Creation(spec=self.config.environment_spec(project_id, host, instance))
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
                project_id,
                instance,
                status="failed",
                stage="failed",
                error=message,
            )
            return

        self.operations.remove(host, project_id, instance)

    def _create(self, creation: _Creation) -> None:
        spec = creation.spec
        project = spec.project
        host = spec.host
        is_repo = project.type == "repo"

        self._stage(creation, "checking inventory", status="running")
        if is_repo:
            creation.token = self._token(self._require_provider(project))
        creation.client = self.transport.client(host)
        creation.route = self.transport.ssh_route(host)
        current = inventory.list_inventory(creation.client, host, self.config)
        self._reject_inventory_errors(host, current)
        self._reject_duplicate_and_collision(
            current.environments,
            spec,
        )

        host_environment: dict[str, str] = {}
        environment_names = self.config.host_config(host).environment
        if environment_names:
            self._stage(creation, "reading host environment")
            host_environment = ssh.read_host_environment(creation.route, environment_names)

        deploy_keypair = None
        if is_repo:
            self._stage(creation, "generating deploy key")
            deploy_keypair = workspace.generate_deploy_keypair()

        self._stage(creation, f"pulling image {spec.image}")
        containers.pull_image(creation.client, spec.image, spec.platform)

        self._stage(creation, "preparing workspace")
        roots = ssh.remote_instance_roots(creation.route)
        ssh.prepare_instance_dirs(
            creation.route,
            [
                spec.instance_path(roots.workspace),
                spec.instance_path(roots.upload),
                spec.instance_path(roots.cache),
            ],
        )

        self._stage(creation, "creating container")
        creation.container_created = True
        container = containers.create_container(
            creation.client,
            spec,
            roots,
            host_environment,
        )

        if deploy_keypair is not None:
            self._stage(creation, "injecting deploy key")
            workspace.inject_deploy_key(container, deploy_keypair.private_key)

        environment = spec.to_environment(container.id, status="running")
        self._stage(creation, "probing ssh")
        ssh.probe(environment, creation.route)

        if is_repo:
            if deploy_keypair is None:
                raise RuntimeError("deploy key missing for repo project")
            if creation.token is None:
                raise RuntimeError("provider token missing for repo project")
            self._stage(creation, "registering deploy key")
            provider.register(
                self._require_provider(project),
                creation.token,
                self._require_repo(project),
                spec.identity,
                deploy_keypair.public_key,
            )
            creation.deploy_key_registered = True

            self._stage(creation, "cloning repository")
            workspace.clone_repo(
                container,
                self._require_repo(project),
                self._require_provider(project),
                spec.clone_path,
            )
        elif project.type == "git":
            self._stage(creation, "cloning repository")
            workspace.clone_git_url(container, self._require_git_url(project), spec.clone_path)
        else:
            self._stage(creation, "preparing open path")
            workspace.prepare_open_path(container, spec.open_path)

        self._stage(creation, "writing ssh config")
        refreshed = inventory.list_inventory(creation.client, host, self.config)
        self._reject_inventory_errors(host, refreshed)
        ssh.write_host(host, refreshed.environments, creation.route)

    def delete(
        self, project_id: str, host: str, instance: str, *, purge: bool, force: bool = False
    ) -> RepoGitState:
        """Inspect when unforced; otherwise delete the environment."""
        project = self._project(project_id)
        self._require_host(project, host)
        spec = self.config.environment_spec(project_id, host, instance)
        is_repo = project.type == "repo"
        token = self._token(self._require_provider(project)) if is_repo else None
        client = self.transport.client(host)
        route = self.transport.ssh_route(host)
        current = inventory.list_inventory(client, host, self.config)
        self._reject_inventory_errors(host, current)
        environment = next(
            (
                item
                for item in current.environments
                if item.project == project_id and item.instance == instance
            ),
            None,
        )
        if environment is None:
            raise RuntimeError(f"environment {spec.identity!r} not found")
        container = inventory.find_container(client, spec, self.config)
        if container is None:
            raise RuntimeError(f"environment {spec.identity!r} not found")

        if not force:
            if is_repo or project.type == "git":
                if environment.status != "running":
                    status = environment.status or "unknown"
                    raise RuntimeError(
                        f"container {spec.identity!r} is {status}; "
                        "repository state cannot be inspected while it is not running"
                    )
                if is_repo:
                    return workspace.repo_git_state(container, spec.clone_path)
                return workspace.git_url_git_state(container, spec.clone_path)
            return RepoGitState()

        if is_repo and token is not None:
            provider.revoke(
                self._require_provider(project),
                token,
                self._require_repo(project),
                spec.identity,
            )
        if purge:
            roots = ssh.remote_instance_roots(route)
            containers.purge_workspace(
                client,
                container,
                environment,
                roots,
            )
        containers.remove_container(container)

        refreshed = inventory.list_inventory(client, host, self.config)
        self._reject_inventory_errors(host, refreshed)
        ssh.write_host(host, refreshed.environments, route)
        return RepoGitState()

    def logs(self, project_id: str, host: str, instance: str) -> str:
        """Return the recent podman logs for one managed container."""
        project = self._project(project_id)
        self._require_host(project, host)
        spec = self.config.environment_spec(project_id, host, instance)
        client = self.transport.client(host)
        container = inventory.find_container(client, spec, self.config)
        if container is None:
            raise RuntimeError(f"environment {spec.identity!r} not found")
        return containers.container_logs(container)

    def _all_host_inventories(self) -> dict[str, dashboard_state.HostInventory]:
        with ThreadPoolExecutor(max_workers=len(self.config.hosts)) as executor:
            inventories = executor.map(self._host_inventory, self.config.hosts)
            return dict(zip(self.config.hosts, inventories, strict=True))

    def _host_inventory(self, host: str) -> dashboard_state.HostInventory:
        try:
            client = self.transport.client(host)
            route = self.transport.ssh_route(host)
            current = inventory.list_inventory(client, host, self.config)
            if not current.errors:
                ssh.write_host(host, current.environments, route)
            return dashboard_state.HostInventory(
                status=HostStatus(
                    id=host,
                    status="online",
                    environment_count=len(current.environments),
                    inventory_errors=current.errors,
                    error="; ".join(current.errors) if current.errors else None,
                ),
                environments=current.environments,
            )
        except Exception as exc:
            return dashboard_state.HostInventory(
                status=HostStatus(id=host, status="offline", error=describe_error(exc)),
                environments=[],
            )

    def _reject_duplicate_and_collision(
        self,
        environments: list[Environment],
        spec: EnvironmentSpec,
    ) -> None:
        for environment in environments:
            if environment.project == spec.project_id and environment.instance == spec.instance:
                raise RuntimeError(f"environment {spec.identity!r} already exists")
            if environment.ssh_port == spec.ssh_port:
                raise RuntimeError(
                    f"SSH port collision on host {spec.host!r}: "
                    f"{spec.identity!r} and {environment.id!r} both map to {spec.ssh_port}; "
                    "choose a different instance name"
                )

    def _rollback_create(self, creation: _Creation) -> Exception | None:
        spec = creation.spec
        if creation.deploy_key_registered:
            if creation.token is None:
                return RuntimeError("provider token is unavailable; container retained")
            try:
                provider.revoke(
                    self._require_provider(spec.project),
                    creation.token,
                    self._require_repo(spec.project),
                    spec.identity,
                )
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
            container = inventory.find_container(
                creation.client,
                spec,
                self.config,
            )
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
            creation.spec.project_id,
            creation.spec.instance,
            status=status,
            stage=stage,
        )

    def _project(self, project_id: str) -> ProjectConfig:
        try:
            return self.config.projects[project_id]
        except KeyError as exc:
            raise KeyError(f"unknown project: {project_id}") from exc

    @staticmethod
    def _require_host(project: ProjectConfig, host: str) -> None:
        if all(entry.name != host for entry in project.host):
            allowed = sorted(entry.name for entry in project.host)
            raise KeyError(f"host {host!r} is not configured for this project; allowed: {allowed}")

    @staticmethod
    def _require_provider(project: ProjectConfig) -> GitProvider:
        if project.provider is None:
            raise RuntimeError("repo project has no provider")
        return project.provider

    @staticmethod
    def _require_repo(project: ProjectConfig) -> str:
        if project.repo is None:
            raise RuntimeError("repo project has no repo")
        return project.repo

    @staticmethod
    def _require_git_url(project: ProjectConfig) -> str:
        if project.git_url is None:
            raise RuntimeError("git project has no git_url")
        return project.git_url

    def _token(self, provider_name: GitProvider) -> str:
        token = self._optional_token(provider_name)
        if token is None:
            raise RuntimeError(f"{provider_name} token is not set")
        return token

    def _optional_token(self, provider_name: GitProvider) -> str | None:
        with self._token_lock:
            return self._tokens.get(provider_name)

    @staticmethod
    def _reject_inventory_errors(host: str, current: inventory.Inventory) -> None:
        if current.errors:
            raise RuntimeError(
                f"host {host!r} has invalid managed inventory: " + "; ".join(current.errors)
            )
