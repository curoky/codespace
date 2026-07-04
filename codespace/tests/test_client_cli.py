"""Tests for the client CLI orchestration (httpx / GitHub / ssh_config mocked)."""

import pytest
from github import GithubException
from typer.testing import CliRunner

from codespace.client import __main__ as cli

runner = CliRunner()


def _codespace_payload(**overrides: object) -> dict:
    data = {
        "id": "abc123",
        "port": 49207,
        "user": "dev",
        "container_id": "cid",
        "repo": "owner/name",
        "workspace": "default",
        "workspace_dir": "codespace-owner-name-default-deadbeef",
        "deploy_keys": [
            {"repo": "owner/name", "public_openssh": "ssh-ed25519 PUB", "read_only": False}
        ],
        "status": "running",
    }
    data.update(overrides)
    return data


def _operation_payload(**overrides: object) -> dict:
    data = {
        "id": "op123",
        "status": "succeeded",
        "stage": "ready",
        "codespace": _codespace_payload(),
        "error": None,
    }
    data.update(overrides)
    return data


@pytest.fixture(autouse=True)
def _stub_login_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Avoid spawning ssh-keygen; return a fixed pubkey. Default to no extra repos
    # so create tests are isolated (individual tests override EXTRA_REPOS).
    monkeypatch.setattr(cli, "_ensure_login_key", lambda alias: "ssh-ed25519 LOGIN")
    monkeypatch.setattr(cli, "EXTRA_REPOS", [])
    monkeypatch.setattr(cli.time, "sleep", lambda _seconds: None)


def test_create_success_registers_key_and_writes_config(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}
    requests: list[tuple[str, str]] = []

    def _request(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
        requests.append((method, url))
        if method == "POST" and url.endswith("/codespaces"):
            return 202, _operation_payload(codespace=None, status="queued", stage="queued")
        if method == "POST" and url.endswith("/clone"):
            return 200, {"ok": True}
        return 200, _operation_payload()

    monkeypatch.setattr(cli, "_request", _request)
    monkeypatch.setattr(
        cli.github,
        "register_deploy_key",
        lambda token, repo, cs_id, pub, *, read_only: (
            calls.setdefault("registered", (repo, cs_id, pub, read_only)) or 1
        ),
    )
    monkeypatch.setattr(cli.ssh_config, "upsert", lambda *a: calls.setdefault("upserted", a))

    result = runner.invoke(
        cli.app,
        [
            "create",
            "--repo",
            "owner/name",
            "--agent",
            "http://h:8080",
            "--ssh-host",
            "10.0.0.5",
            "--token",
            "tok",
        ],
    )

    assert result.exit_code == 0
    assert requests == [
        ("POST", "http://h:8080/codespaces"),
        ("GET", "http://h:8080/operations/op123"),
        ("POST", "http://h:8080/codespaces/abc123/clone"),
    ]
    assert calls["registered"] == ("owner/name", "abc123", "ssh-ed25519 PUB", False)
    # upsert(alias, ssh_host, port, user, id, repos)
    assert calls["upserted"] == ("name", "10.0.0.5", 49207, "dev", "abc123", ["owner/name"])


def test_create_registers_extra_repo_readonly(monkeypatch: pytest.MonkeyPatch) -> None:
    registered: list[tuple[str, bool]] = []
    monkeypatch.setattr(cli, "EXTRA_REPOS", ["owner/dotfiles"])
    payload = _codespace_payload(
        deploy_keys=[
            {"repo": "owner/name", "public_openssh": "ssh-ed25519 MAIN", "read_only": False},
            {"repo": "owner/dotfiles", "public_openssh": "ssh-ed25519 EXTRA", "read_only": True},
        ]
    )
    monkeypatch.setattr(
        cli,
        "_request",
        lambda method, url, body=None: (
            (202, _operation_payload(codespace=None))
            if method == "POST" and url.endswith("/codespaces")
            else (200, {"ok": True})
            if method == "POST" and url.endswith("/clone")
            else (200, _operation_payload(codespace=payload))
        ),
    )
    monkeypatch.setattr(
        cli.github,
        "register_deploy_key",
        lambda token, repo, cs_id, pub, *, read_only: registered.append((repo, read_only)) or 1,
    )
    upserted: dict[str, object] = {}
    monkeypatch.setattr(cli.ssh_config, "upsert", lambda *a: upserted.setdefault("repos", a[5]))

    result = runner.invoke(
        cli.app,
        [
            "create",
            "--repo",
            "owner/name",
            "--agent",
            "http://h:8080",
            "--ssh-host",
            "10.0.0.5",
            "--token",
            "tok",
        ],
    )

    assert result.exit_code == 0
    assert registered == [("owner/name", False), ("owner/dotfiles", True)]
    assert upserted["repos"] == ["owner/name", "owner/dotfiles"]


def test_create_rolls_back_when_registration_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []
    removed: list[str] = []
    monkeypatch.setattr(
        cli,
        "_request",
        lambda method, url, body=None: (
            (202, _operation_payload(codespace=None))
            if method == "POST"
            else (200, _operation_payload())
        ),
    )
    monkeypatch.setattr(cli, "_delete_remote", lambda agent, cs_id: deleted.append(cs_id))
    monkeypatch.setattr(cli, "_remove_login_key", lambda alias: removed.append(alias))

    def _boom(*a: object, **k: object) -> int:
        raise GithubException(status=422, data={"message": "exists"})

    monkeypatch.setattr(cli.github, "register_deploy_key", _boom)

    result = runner.invoke(
        cli.app,
        [
            "create",
            "--repo",
            "owner/name",
            "--agent",
            "http://h:8080",
            "--ssh-host",
            "10.0.0.5",
            "--token",
            "tok",
        ],
    )

    assert result.exit_code == 1
    assert deleted == ["abc123"]  # container rolled back
    assert removed == ["name"]  # local login key cleaned up


def test_create_rolls_back_when_clone_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[str] = []
    removed: list[str] = []
    revoked: list[str] = []

    def _request(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
        if method == "POST" and url.endswith("/codespaces"):
            return 202, _operation_payload(codespace=None)
        if method == "POST" and url.endswith("/clone"):
            return 500, {"error": "clone failed"}
        return 200, _operation_payload()

    monkeypatch.setattr(cli, "CLONE_ATTEMPTS", 1)
    monkeypatch.setattr(cli, "_request", _request)
    monkeypatch.setattr(cli, "_delete_remote", lambda agent, cs_id: deleted.append(cs_id))
    monkeypatch.setattr(cli, "_remove_login_key", lambda alias: removed.append(alias))
    monkeypatch.setattr(cli, "_revoke_quietly", lambda token, repo, cs_id: revoked.append(repo))
    monkeypatch.setattr(cli.github, "register_deploy_key", lambda *a, **k: 1)

    result = runner.invoke(
        cli.app,
        [
            "create",
            "--repo",
            "owner/name",
            "--agent",
            "http://h:8080",
            "--ssh-host",
            "10.0.0.5",
            "--token",
            "tok",
        ],
    )

    assert result.exit_code == 1
    assert "clone failed" in result.output
    assert revoked == ["owner/name"]
    assert deleted == ["abc123"]
    assert removed == ["name"]


def test_create_fails_when_agent_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "_request", lambda *a, **k: (500, {"error": "podman down"}))
    removed: list[str] = []
    monkeypatch.setattr(cli, "_remove_login_key", lambda alias: removed.append(alias))
    result = runner.invoke(
        cli.app,
        [
            "create",
            "--repo",
            "owner/name",
            "--agent",
            "http://h:8080",
            "--ssh-host",
            "10.0.0.5",
            "--token",
            "tok",
        ],
    )
    assert result.exit_code == 1
    assert "podman down" in result.output
    assert removed == ["name"]


def test_create_fails_when_operation_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    removed: list[str] = []
    monkeypatch.setattr(cli, "_remove_login_key", lambda alias: removed.append(alias))
    monkeypatch.setattr(
        cli,
        "_request",
        lambda method, url, body=None: (
            (202, _operation_payload(codespace=None))
            if method == "POST" and url.endswith("/codespaces")
            else (200, _operation_payload(status="failed", codespace=None, error="pull failed"))
        ),
    )

    result = runner.invoke(
        cli.app,
        [
            "create",
            "--repo",
            "owner/name",
            "--agent",
            "http://h:8080",
            "--ssh-host",
            "10.0.0.5",
            "--token",
            "tok",
        ],
    )

    assert result.exit_code == 1
    assert "pull failed" in result.output
    assert removed == ["name"]


def test_delete_revokes_key_then_removes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setattr(cli.ssh_config, "get_id", lambda alias: "abc123")
    monkeypatch.setattr(cli.ssh_config, "get_repos", lambda alias: ["owner/name"])
    monkeypatch.setattr(
        cli.github,
        "delete_deploy_key",
        lambda token, repo, cs_id: calls.setdefault("revoked", (repo, cs_id)) or True,
    )
    monkeypatch.setattr(
        cli, "_request", lambda *a, **k: (200, {"ok": True, "workspace_removed": False})
    )
    monkeypatch.setattr(cli.ssh_config, "remove", lambda alias: calls.setdefault("removed", alias))
    monkeypatch.setattr(
        cli, "_remove_login_key", lambda alias: calls.setdefault("key_removed", alias)
    )

    result = runner.invoke(
        cli.app, ["delete", "--alias", "name-default", "--agent", "http://h:8080", "--token", "tok"]
    )

    assert result.exit_code == 0
    assert calls["revoked"] == ("owner/name", "abc123")
    assert calls["removed"] == "name-default"
    assert calls["key_removed"] == "name-default"


def test_delete_fails_without_resolvable_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.ssh_config, "get_id", lambda alias: None)
    result = runner.invoke(
        cli.app, ["delete", "--alias", "ghost", "--agent", "http://h:8080", "--token", "tok"]
    )
    assert result.exit_code == 1
    assert "cannot resolve codespace id" in result.output


def test_list_renders_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "_request", lambda *a, **k: (200, [_codespace_payload(status="running")])
    )
    result = runner.invoke(cli.app, ["list", "--agent", "http://h:8080", "--ssh-host", "10.0.0.5"])
    assert result.exit_code == 0
    assert "abc123" in result.output
    assert "owner/name" in result.output
