"""GitLab deploy-key lifecycle, owned entirely by the client."""

from urllib.parse import quote

import httpx

from codespace import shared

HTTP_TIMEOUT = 30.0


def register_deploy_key(
    token: str,
    api_url: str,
    repo: str,
    cs_id: str,
    public_openssh: str,
    *,
    read_only: bool = False,
) -> int:
    """Register ``public_openssh`` as a GitLab deploy key on ``repo``; return its id."""
    response = httpx.post(
        _project_url(api_url, repo, "deploy_keys"),
        headers=_headers(token),
        json={
            "title": shared.deploy_key_title(cs_id),
            "key": public_openssh,
            "can_push": not read_only,
        },
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    return int(response.json()["id"])


def delete_deploy_key(token: str, api_url: str, repo: str, cs_id: str) -> bool:
    """Delete the GitLab deploy key titled ``codespace-<cs_id>`` from ``repo``."""
    title = shared.deploy_key_title(cs_id)
    response = httpx.get(
        _project_url(api_url, repo, "deploy_keys"),
        headers=_headers(token),
        timeout=HTTP_TIMEOUT,
    )
    response.raise_for_status()
    removed = False
    for key in response.json():
        if key.get("title") == title:
            delete_response = httpx.delete(
                _project_url(api_url, repo, f"deploy_keys/{key['id']}"),
                headers=_headers(token),
                timeout=HTTP_TIMEOUT,
            )
            delete_response.raise_for_status()
            removed = True
    return removed


def _headers(token: str) -> dict[str, str]:
    return {"PRIVATE-TOKEN": token}


def _project_url(api_url: str, repo: str, path: str) -> str:
    return f"{api_url.rstrip('/')}/api/v4/projects/{quote(repo, safe='')}/{path.lstrip('/')}"
