"""Credential loading failures must not expose captured plaintext."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from codespace import credentials
from codespace.config import Config
from codespace.control import ControlPlane


@pytest.fixture
def csecret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    executable = (
        tmp_path / "workspace/codespace/platform/container/workspace/tools/csecret/csecret.sh"
    )
    executable.parent.mkdir(parents=True)
    executable.write_text(
        "#!/bin/sh\n"
        '[ "$1" = get ] || exit 2\n'
        'case "$2" in\n'
        "  codespace_github_token) printf 'fixture-github-token' ;;\n"
        "  codespace_gitlab_token) printf 'fixture-gitlab-token' ;;\n"
        "  *) printf 'private-output'; printf 'private-error' >&2; exit 1 ;;\n"
        "esac\n"
    )
    executable.chmod(0o755)
    return executable


def test_load_tokens_reads_canonical_keys(csecret: Path) -> None:
    del csecret
    assert credentials.load_tokens() == {
        "github": "fixture-github-token",
        "gitlab": "fixture-gitlab-token",
    }


@pytest.mark.parametrize("output", ["", " \n", "private-output"])
def test_failed_or_empty_credentials_do_not_expose_output(csecret: Path, output: str) -> None:
    csecret.write_text(
        "#!/bin/sh\n"
        "printf '%s' '" + output + "'\n"
        "printf 'private-error' >&2\n" + ("exit 1\n" if output == "private-output" else "")
    )
    with pytest.raises(RuntimeError) as error:
        credentials.load_tokens()
    assert str(error.value) == "cannot load github token from csecret key 'codespace_github_token'"
    assert error.value.__cause__ is None
    assert "private-output" not in str(error.value)
    assert "private-error" not in str(error.value)


def test_missing_executable_fails(csecret: Path) -> None:
    csecret.unlink()
    with pytest.raises(RuntimeError, match="cannot load github token"):
        credentials.load_tokens()


def test_missing_gitlab_key_does_not_return_partial_credentials(csecret: Path) -> None:
    csecret.write_text(
        csecret.read_text().replace("codespace_gitlab_token)", "unavailable_gitlab_token)")
    )
    with pytest.raises(RuntimeError, match="cannot load gitlab token"):
        credentials.load_tokens()


def test_timeout_does_not_expose_captured_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired(
            "csecret", 30, output="private-output", stderr="private-error"
        )

    monkeypatch.setattr(credentials.subprocess, "run", timeout)
    with pytest.raises(RuntimeError) as error:
        credentials.load_tokens()
    assert str(error.value) == "cannot load github token from csecret key 'codespace_github_token'"
    assert error.value.__cause__ is None


def test_control_loads_before_opening_transport_and_keeps_values_out_of_config(
    csecret: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = Config.model_validate(
        {
            "hosts": {},
            "project_defaults": {"resource_image": "resource", "container": {"image": "workspace"}},
        }
    )
    control = ControlPlane(config, transport=SimpleNamespace())  # type: ignore[arg-type]
    assert control._token("github") == "fixture-github-token"
    assert control.token_status() == {"github": True, "gitlab": True}
    assert "fixture-github-token" not in str(config.model_dump())

    def unexpected_transport(*_args: object, **_kwargs: object) -> None:
        pytest.fail("transport must not open when credential resolution fails")

    monkeypatch.setattr("codespace.control.PodmanTransport", unexpected_transport)
    csecret.unlink()
    with pytest.raises(RuntimeError, match="cannot load github token"):
        ControlPlane(config)
