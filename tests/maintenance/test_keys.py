"""Tests for unused deploy-key classification."""

import pytest

from codespace.maintenance import keys


@pytest.mark.parametrize(
    ("title", "active", "scanned", "expected"),
    [
        (
            "codespace-workspace_home_codespace_live",
            {"codespace-workspace_home_codespace_live"},
            {"home"},
            "yes",
        ),
        ("codespace-workspace_home_codespace_old", set(), {"home"}, "no"),
        ("codespace-workspace_office_codespace_live", set(), {"home"}, "unknown"),
        ("manual-key", set(), {"home"}, "unmanaged"),
    ],
)
def test_usage(
    title: str,
    active: set[str],
    scanned: set[str],
    expected: str,
) -> None:
    routes = [("home", "codespace"), ("office", "codespace")]

    assert keys._usage(title, routes, active, scanned) == expected
