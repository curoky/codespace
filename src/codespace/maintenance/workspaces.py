"""Plan and delete Workspace data without a matching managed container."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Literal

from rich.console import Console

from codespace.config import CONFIG_PATH, Config, load_config
from codespace.maintenance import output
from codespace.runtime import container, host
from codespace.runtime.transport import PodmanTransport
from codespace.workspaces import inventory
from codespace.workspaces.models import RESOURCE_ID_RE

type Usage = Literal["yes", "no", "unmanaged"]
type Candidate = tuple[str, str, str]


def prune(
    *,
    apply: bool,
    config_path: Path = CONFIG_PATH,
    console: Console | None = None,
) -> None:
    """Show all orphan Workspace directories, then optionally delete them."""
    target = console or Console()
    config = load_config(config_path)
    transport = PodmanTransport({name: value.endpoint() for name, value in config.hosts.items()})
    try:
        candidates, errors = _collect(config, transport)
        rows = [
            (host_name, root, path, _usage(root, path, active))
            for host_name, root, path, active in candidates
        ]
        output.render_table(
            target,
            [
                {"header": "Host"},
                {"header": "Workspace", "overflow": "fold"},
                {"header": "In use", "no_wrap": True},
            ],
            [(host_name, path, usage) for host_name, _root, path, usage in rows],
        )
        output.print_warnings(target, errors)
        unused = [(host_name, root, path) for host_name, root, path, usage in rows if usage == "no"]
        if not apply:
            target.print(f"Dry run: {len(unused)} unused Workspace(s); pass --apply to delete.")
            return
        deleted, delete_errors = _delete(config, transport, unused)
        output.print_errors(target, delete_errors)
        target.print(f"Deleted {deleted} unused Workspace(s).")
    finally:
        transport.close()


def _collect(
    config: Config,
    transport: PodmanTransport,
) -> tuple[list[tuple[str, str, str, set[str]]], list[str]]:
    scanned_by_host, failures = output.fan_out(
        config.hosts,
        lambda host_name: _scan_host(transport, host_name),
    )
    candidates = [
        (host_name, root, path, active)
        for host_name, (scanned, active) in scanned_by_host
        for root, path in scanned
    ]
    candidates.sort(key=lambda item: (item[0], item[2]))
    return candidates, [f"{host_name}: {exc}" for host_name, exc in failures]


def _scan_host(
    transport: PodmanTransport,
    host_name: str,
) -> tuple[list[tuple[str, str]], set[str]]:
    route = transport.ssh_route(host_name)
    data_paths = host.remote_data_paths(route)
    root = data_paths.workspaces
    scanned = [(root, path) for path in host.list_workspaces(route, root)]
    active = {
        data_paths.workspace(workspace.project, workspace.workspace).root
        for workspace in inventory.list_workspaces(transport.client(host_name), host_name)
    }
    return scanned, active


def _usage(root: str, path: str, active: set[str]) -> Usage:
    try:
        relative = PurePosixPath(path).relative_to(PurePosixPath(root))
    except ValueError:
        return "unmanaged"
    if len(relative.parts) != 2 or any(
        not RESOURCE_ID_RE.fullmatch(part) for part in relative.parts
    ):
        return "unmanaged"
    return "yes" if path in active else "no"


def _delete(
    config: Config,
    transport: PodmanTransport,
    workspaces: list[Candidate],
) -> tuple[int, list[str]]:
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for host_name, root, path in workspaces:
        grouped[host_name].append((root, path))
    results, failures = output.fan_out(
        grouped,
        lambda host_name: _delete_host(
            transport,
            host_name,
            config.project_defaults.image,
            grouped[host_name],
        ),
    )
    deleted = sum(count for _host, (count, _errors) in results)
    errors = [
        f"{host_name}: {error}"
        for host_name, (_count, host_errors) in results
        for error in host_errors
    ]
    errors.extend(f"{host_name}: {exc}" for host_name, exc in failures)
    return deleted, errors


def _delete_host(
    transport: PodmanTransport,
    host_name: str,
    image: str,
    workspaces: list[tuple[str, str]],
) -> tuple[int, list[str]]:
    client = transport.client(host_name)
    deleted = 0
    errors: list[str] = []
    for root, path in workspaces:
        try:
            container.remove_data_directory(client, image, root, path)
            deleted += 1
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    return deleted, errors
