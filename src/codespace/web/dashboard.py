"""Build the browser-facing Dashboard from live Host inventory."""

from __future__ import annotations

from codespace.control import ControlPlane, HostFailure, HostInventory
from codespace.workspaces import editor_url


def build(control: ControlPlane) -> dict[str, object]:
    config = control.config
    collected = control.inventory()
    inventories = [result for result in collected.values() if isinstance(result, HostInventory)]
    workspaces = [workspace for inventory in inventories for workspace in inventory.workspaces]
    services = {
        (service.host, service.service): service
        for inventory in inventories
        for service in inventory.services
    }
    return {
        "hosts": [
            {
                "id": result.host,
                "status": result.status,
                "workspace_count": None,
                "error": result.error,
            }
            if isinstance(result, HostFailure)
            else {
                "id": result.host,
                "status": "online",
                "workspace_count": len(result.workspaces),
                "error": None,
            }
            for result in collected.values()
        ],
        "projects": [
            {
                "id": project_id,
                "hosts": [
                    {
                        "name": host_name,
                        "platform": config.resolved_project_container(
                            project_id, host_name
                        ).platform,
                        "image": config.resolved_project_container(project_id, host_name).image,
                    }
                    for host_name in project.hosts
                ],
                "source": project.source,
                "description": project.description,
                "open_path": project.resolved_open_path(),
                "tunnel_ports": config.project_tunnel_ports(project_id),
            }
            for project_id, project in config.projects.items()
        ],
        "workspaces": [
            {
                **workspace.model_dump(exclude={"container_id"}),
                "ssh_command": f"ssh {workspace.ssh_alias}",
                "trae_url": editor_url(workspace.ssh_alias, workspace.open_path),
                "trae_cn_url": editor_url(
                    workspace.ssh_alias, workspace.open_path, scheme="trae-cn"
                ),
                "vscode_url": editor_url(workspace.ssh_alias, workspace.open_path, scheme="vscode"),
            }
            for workspace in sorted(
                workspaces,
                key=lambda item: (item.project, item.workspace),
            )
        ],
        "services": [
            {
                "id": service_id,
                "hosts": [
                    {
                        "host": host_name,
                        "desired_image": config.resolved_service_container(
                            service_id, host_name
                        ).image,
                        "tunnel_ports": config.service_tunnel_ports(service_id, host_name),
                        "container": services.get((host_name, service_id)),
                    }
                    for host_name in service.hosts
                ],
            }
            for service_id, service in config.services.items()
        ],
        "operations": sorted(control.operations.list(), key=lambda item: item.kind == "service"),
        "tokens": control.token_status(),
    }
