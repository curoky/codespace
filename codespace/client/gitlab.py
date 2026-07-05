"""GitLab deploy-key lifecycle, owned entirely by the client."""

import gitlab as python_gitlab

from codespace import shared

HTTP_TIMEOUT = 30.0


def register_deploy_key(
    token: str,
    repo: str,
    cs_id: str,
    public_openssh: str,
    *,
    read_only: bool = False,
) -> int:
    """Register ``public_openssh`` as a GitLab deploy key on ``repo``; return its id."""
    client = python_gitlab.Gitlab(private_token=token, timeout=HTTP_TIMEOUT)
    project = client.projects.get(repo)
    deploy_key = project.keys.create(
        {
            "title": shared.deploy_key_title(cs_id),
            "key": public_openssh,
            "can_push": not read_only,
        }
    )
    return int(deploy_key.id)


def delete_deploy_key(token: str, repo: str, cs_id: str) -> bool:
    """Delete the GitLab deploy key titled ``codespace-<cs_id>`` from ``repo``."""
    client = python_gitlab.Gitlab(private_token=token, timeout=HTTP_TIMEOUT)
    project = client.projects.get(repo)
    title = shared.deploy_key_title(cs_id)
    removed = False
    for key in project.keys.list(get_all=True):
        if key.title == title:
            project.keys.delete(key.id)
            removed = True
    return removed
