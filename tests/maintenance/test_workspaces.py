"""Tests for orphan Workspace cleanup."""

import pytest

from codespace.maintenance import workspaces


@pytest.mark.parametrize(
    ("path", "active", "expected"),
    [
        (
            "/home/x/codespace/workspaces/codespace/live",
            {"/home/x/codespace/workspaces/codespace/live"},
            "yes",
        ),
        ("/home/x/codespace/workspaces/codespace/old", set(), "no"),
        ("/home/x/codespace/workspaces/Invalid/old", set(), "unmanaged"),
        ("/home/x/other/codespace/old", set(), "unmanaged"),
    ],
)
def test_usage(path: str, active: set[str], expected: str) -> None:
    assert workspaces._usage("/home/x/codespace/workspaces", path, active) == expected
