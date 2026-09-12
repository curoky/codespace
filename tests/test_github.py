"""GitHub CLI authentication uses a private secret during Workspace startup."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SERVICE = _ROOT / "platform/container/workspace/rootfs/etc/s6/s6-rc.d/gh-login"


def test_gh_login_is_a_home_gated_default_oneshot() -> None:
    assert (_SERVICE / "type").read_text().strip() == "oneshot"
    assert (_SERVICE / "dependencies.d/home-init").is_file()
    assert (_SERVICE.parent / "default/contents.d/gh-login").is_file()


def test_gh_login_reads_token_from_secret_stdin() -> None:
    up = (_SERVICE / "up").read_text()

    assert "redirfd -w 1 /var/log/s6.gh-login.log" in up
    assert "if { test -s /run/secrets/github_action_token }" in up
    assert "s6-setuidgid x" in up
    assert "s6-env HOME=/home/x" in up
    assert "redirfd -r 0 /run/secrets/github_action_token" in up
    assert "gh auth login" in up
    assert "--hostname github.com" in up
    assert "--git-protocol ssh" in up
    assert "--skip-ssh-key" in up
    assert "--insecure-storage" in up
    assert "--with-token" in up
    assert "GH_TOKEN" not in up
