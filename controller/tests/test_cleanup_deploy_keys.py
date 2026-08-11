"""Tests for the deploy-key cleanup tool."""

from __future__ import annotations

from io import StringIO

import pytest
from rich.console import Console
from typer.testing import CliRunner

from controller import provider
from controller.config import Config
from controller.tools import cleanup_deploy_keys


@pytest.fixture
def config() -> Config:
    return Config.model_validate(
        {
            "default_image": "image",
            "container": {"network_mode": "host"},
            "hosts": {"home": {}, "office": {}},
            "tokens": {"github": "token"},
            "projects": {
                "devspace": {
                    "repo": "github:owner/repo",
                    "host": [{"name": "home"}, {"name": "office"}],
                }
            },
        }
    )


@pytest.mark.parametrize(
    ("title", "active", "scanned_hosts", "expected"),
    [
        ("codespace-home-devspace-live", {"codespace-home-devspace-live"}, {"home"}, "yes"),
        ("codespace-home-devspace-old", set(), {"home"}, "no"),
        ("codespace-office-devspace-live", set(), {"home"}, "unknown"),
        ("codespace-removed-project-old", set(), {"home"}, "no"),
        ("manual-key", set(), {"home"}, "unmanaged"),
    ],
)
def test_usage(
    title: str,
    active: set[str],
    scanned_hosts: set[str],
    expected: str,
) -> None:
    routes = [("home", "devspace"), ("office", "devspace")]

    assert cleanup_deploy_keys._usage(title, routes, active, scanned_hosts) == expected


@pytest.mark.parametrize("arguments", [[], ["--no-dry-run"]])
def test_cli_prints_table_and_only_deletes_with_no_dry_run(
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
    arguments: list[str],
) -> None:
    repository = ("github", "owner/repo")
    keys = {
        repository: [
            provider.DeployKey(1, "codespace-home-devspace-live"),
            provider.DeployKey(2, "codespace-home-devspace-old"),
        ]
    }
    output = StringIO()
    deleted: list[list[tuple[tuple[str, str], provider.DeployKey]]] = []
    monkeypatch.setattr(cleanup_deploy_keys, "console", Console(file=output, width=120))
    monkeypatch.setattr(cleanup_deploy_keys, "load_config", lambda _path: config)
    monkeypatch.setattr(
        cleanup_deploy_keys,
        "_collect",
        lambda _config, _repositories: (
            keys,
            {"codespace-home-devspace-live"},
            {"home", "office"},
            [],
        ),
    )
    monkeypatch.setattr(
        cleanup_deploy_keys,
        "_delete",
        lambda _config, unused: (deleted.append(list(unused)) or len(unused), []),
    )

    result = CliRunner().invoke(cleanup_deploy_keys.app, arguments)

    assert result.exit_code == 0
    rendered = output.getvalue()
    assert "Repository" in rendered
    assert "Deploy key" in rendered
    assert "In use" in rendered
    assert "github:owner/repo" in rendered
    assert "codespace-home-devspace-live" in rendered
    assert "codespace-home-devspace-old" in rendered
    if arguments:
        assert len(deleted) == 1
        assert deleted[0][0][1].id == 2
        assert "Deleted 1 unused key(s)." in rendered
    else:
        assert deleted == []
        assert "Dry run: 1 unused key(s)" in rendered
