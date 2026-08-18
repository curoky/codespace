"""Read and validate managed Podman environments."""

from __future__ import annotations

from dataclasses import dataclass

from podman import PodmanClient
from podman.domain.containers import Container
from podman.errors import NotFound

from controller.config import Config, ProjectConfig
from controller.models import (
    GIT_URL_RE,
    LABEL_GIT_URL,
    LABEL_IMAGE,
    LABEL_INSTANCE,
    LABEL_MANAGED,
    LABEL_PLATFORM,
    LABEL_PROJECT,
    LABEL_PROVIDER,
    LABEL_REPO,
    LABEL_SSH_PORT,
    LABEL_TYPE,
    MANDATORY_LABELS,
    REPO_RE,
    RESOURCE_ID_RE,
    Environment,
    EnvironmentSpec,
    GitProvider,
    PlatformSelection,
    ProjectType,
    environment_id,
    ssh_port,
)


@dataclass(frozen=True, slots=True)
class Inventory:
    environments: list[Environment]
    errors: list[str]


def list_inventory(client: PodmanClient, host: str, config: Config) -> Inventory:
    """Return valid environments and explicit errors for damaged inventory."""
    environments: list[Environment] = []
    errors: list[str] = []
    containers = client.containers.list(
        all=True,
        filters={"label": f"{LABEL_MANAGED}=true"},
    )
    for container in containers:
        try:
            environments.append(read_environment(container, host, config))
        except ValueError as exc:
            errors.append(str(exc))
    environments.sort(key=lambda environment: (environment.project, environment.instance))
    return Inventory(environments=environments, errors=errors)


def read_environment(container: Container, host: str, config: Config) -> Environment:
    """Validate one container against the managed label contract."""
    name = _container_name(container)
    raw_labels = container.labels or {}
    if raw_labels.get(LABEL_MANAGED) != "true":
        raise ValueError(f"container {name} has invalid label {LABEL_MANAGED}")
    labels = {key: _required_label(raw_labels, name, key) for key in MANDATORY_LABELS}
    project = labels[LABEL_PROJECT]
    instance = labels[LABEL_INSTANCE]
    project_type = _project_type(labels[LABEL_TYPE], name)

    if not RESOURCE_ID_RE.fullmatch(project):
        raise ValueError(f"container {name} has invalid project label {project!r}")
    if not RESOURCE_ID_RE.fullmatch(instance):
        raise ValueError(f"container {name} has invalid instance label {instance!r}")
    if project not in config.projects:
        raise ValueError(f"container {name} references unknown project {project!r}")
    configured_project = config.projects[project]
    if all(entry.name != host for entry in configured_project.host):
        allowed = sorted(entry.name for entry in configured_project.host)
        raise ValueError(
            f"container {name} project {project!r} is not configured for host "
            f"{host!r}; allowed hosts: {allowed}"
        )
    if configured_project.type != project_type:
        raise ValueError(
            f"container {name} type {project_type!r} does not match project {project!r}"
        )

    repo, provider = _read_repo_labels(raw_labels, name, project_type, configured_project)
    git_url = _read_git_url_label(raw_labels, name, project_type, configured_project)
    identity = environment_id(host, project, instance)
    if name != identity:
        raise ValueError(f"container {name} must use deterministic name {identity!r}")
    try:
        port = int(labels[LABEL_SSH_PORT])
    except ValueError as exc:
        raise ValueError(
            f"container {name} has invalid SSH port label {labels[LABEL_SSH_PORT]!r}"
        ) from exc
    expected_port = ssh_port(identity)
    if port != expected_port:
        raise ValueError(f"container {name} has SSH port {port}, expected {expected_port}")

    return Environment(
        id=identity,
        host=host,
        project=project,
        instance=instance,
        type=project_type,
        repo=repo,
        provider=provider,
        git_url=git_url,
        image=labels[LABEL_IMAGE],
        platform=_platform(labels[LABEL_PLATFORM], name),
        ssh_port=port,
        container_id=container.id,
        status=container_status(container),
    )


def find_container(
    client: PodmanClient,
    spec: EnvironmentSpec,
    config: Config,
) -> Container | None:
    """Find and validate the deterministic container for a resolved instance."""
    try:
        container = client.containers.get(spec.identity)
    except NotFound:
        return None
    environment = read_environment(container, spec.host, config)
    if environment.project != spec.project_id or environment.instance != spec.instance:
        raise ValueError(f"container {spec.identity} has mismatched identity labels")
    return container


def container_status(container: Container) -> str | None:
    state = container.attrs.get("State")
    if isinstance(state, str):
        return state or None
    if isinstance(state, dict):
        status = state.get("Status")
        return str(status) if status else None
    return None


def _read_repo_labels(
    labels: dict[str, str],
    name: str,
    project_type: ProjectType,
    configured_project: ProjectConfig,
) -> tuple[str | None, GitProvider | None]:
    if project_type != "repo":
        if labels.get(LABEL_REPO) or labels.get(LABEL_PROVIDER):
            raise ValueError(f"container {name} is {project_type} but has repo or provider label")
        return None, None
    repo = _required_label(labels, name, LABEL_REPO)
    provider = _provider(_required_label(labels, name, LABEL_PROVIDER), name)
    if not REPO_RE.fullmatch(repo):
        raise ValueError(f"container {name} has invalid repo label {repo!r}")
    if configured_project.repo != repo or configured_project.provider != provider:
        raise ValueError(f"container {name} labels do not match project labels")
    return repo, provider


def _read_git_url_label(
    labels: dict[str, str],
    name: str,
    project_type: ProjectType,
    configured_project: ProjectConfig,
) -> str | None:
    if project_type != "git":
        if labels.get(LABEL_GIT_URL):
            raise ValueError(f"container {name} is {project_type} but has git-url label")
        return None
    git_url = _required_label(labels, name, LABEL_GIT_URL)
    if not GIT_URL_RE.fullmatch(git_url):
        raise ValueError(f"container {name} has invalid git-url label {git_url!r}")
    if configured_project.git_url != git_url:
        raise ValueError(f"container {name} labels do not match project labels")
    return git_url


def _container_name(container: Container) -> str:
    return str(getattr(container, "name", None) or container.id)


def _required_label(labels: dict[str, str], name: str, key: str) -> str:
    value = labels.get(key)
    if value is None or not value.strip():
        raise ValueError(f"container {name} is missing required label {key}")
    return value


def _provider(value: str, name: str) -> GitProvider:
    match value:
        case "github":
            return "github"
        case "gitlab":
            return "gitlab"
        case _:
            raise ValueError(f"container {name} has invalid provider label {value!r}")


def _project_type(value: str, name: str) -> ProjectType:
    match value:
        case "repo":
            return "repo"
        case "blank":
            return "blank"
        case "git":
            return "git"
        case _:
            raise ValueError(f"container {name} has invalid type label {value!r}")


def _platform(value: str, name: str) -> PlatformSelection:
    match value:
        case "native":
            return "native"
        case "linux/amd64":
            return "linux/amd64"
        case "linux/arm64":
            return "linux/arm64"
        case _:
            raise ValueError(f"container {name} has invalid platform label {value!r}")
