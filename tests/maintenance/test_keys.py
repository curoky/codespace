"""Tests for unused deploy-key classification."""

import pytest

from codespace.maintenance import keys


@pytest.mark.parametrize(
    ("title", "active", "scanned", "expected"),
    [
        (
            "codespace-workspace-home-codespace-live",
            {"codespace-workspace-home-codespace-live"},
            {"home"},
            "yes",
        ),
        ("codespace-workspace-home-codespace-old", set(), {"home"}, "no"),
        ("codespace-workspace-office-codespace-live", set(), {"home"}, "unknown"),
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
