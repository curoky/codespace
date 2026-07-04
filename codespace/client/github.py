"""GitHub deploy-key lifecycle, owned entirely by the client.

The client holds the GitHub token (it never crosses the network to the agent).
Keys are correlated to a codespace purely by title ``codespace-<cs_id>`` so a
key can be found and deleted from the ``cs_id`` alone, without persisting its
numeric id (see DESIGN.md §6/§9).
"""

from github import Auth, Github

from codespace import shared


def register_deploy_key(
    token: str,
    repo: str,
    cs_id: str,
    public_openssh: str,
    *,
    read_only: bool = False,
) -> int:
    """Register ``public_openssh`` as a deploy key on ``repo``; return its id.

    The key is titled ``codespace-<cs_id>`` so it can later be rediscovered by
    title. ``read_only`` is ``False`` for the main repo (push access) and
    ``True`` for extra repos (pull-only).
    """
    with Github(auth=Auth.Token(token)) as gh:
        repository = gh.get_repo(repo)
        key = repository.create_key(
            title=shared.deploy_key_title(cs_id),
            key=public_openssh,
            read_only=read_only,
        )
        return key.id


def delete_deploy_key(token: str, repo: str, cs_id: str) -> bool:
    """Delete the deploy key titled ``codespace-<cs_id>`` from ``repo``.

    Rediscovers the key by title rather than a stored id, so cleanup stays
    robust even if local state was lost. Returns ``True`` if a key was removed,
    ``False`` if none matched (idempotent).
    """
    title = shared.deploy_key_title(cs_id)
    removed = False
    with Github(auth=Auth.Token(token)) as gh:
        repository = gh.get_repo(repo)
        for key in repository.get_keys():
            if key.title == title:
                key.delete()
                removed = True
    return removed
