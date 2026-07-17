"""GitLab deploy-key lifecycle, owned entirely by the client."""

import gitlab as python_gitlab

from codespace import shared

HTTP_TIMEOUT = 30.0


def register_deploy_key(
    token: str,
    repo: str,
    cs_id: str,
    public_openssh: str,
) -> int:
    """Register ``public_openssh`` as a GitLab deploy key on ``repo``; return its id."""
    client = python_gitlab.Gitlab(private_token=token, timeout=HTTP_TIMEOUT)
    # Fine-grained PATs can be limited to deploy-key endpoints only. Avoid an
    # eager GET /projects/:id here because that endpoint may require a different
    # permission even when the deploy-key endpoints themselves are allowed.
    project = client.projects.get(repo, lazy=True)
    deploy_key = project.keys.create(
        {
            "title": shared.deploy_key_title(cs_id),
            "key": public_openssh,
            "can_push": True,
        }
    )
    return int(deploy_key.id)


def delete_deploy_key(token: str, repo: str, cs_id: str) -> bool:
    """Delete the GitLab deploy key titled ``codespace-<cs_id>`` from ``repo``."""
    client = python_gitlab.Gitlab(private_token=token, timeout=HTTP_TIMEOUT)
    # Keep this lazy for GitLab fine-grained PATs with only deploy-key access.
    project = client.projects.get(repo, lazy=True)
    title = shared.deploy_key_title(cs_id)
    removed = False
    for key in project.keys.list(get_all=True):
        if key.title == title:
            project.keys.delete(key.id)
            removed = True
    return removed
