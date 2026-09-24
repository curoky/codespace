from __future__ import annotations

import importlib.util
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


def load_node_tool() -> ModuleType:
    source = Path(__file__).with_name("node-tool.py")
    spec = importlib.util.spec_from_file_location("node_tool", source)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


node_tool = load_node_tool()


def make_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def create_fake_node(tmp_path: Path) -> Path:
    node_root = tmp_path / "node"
    make_executable(
        node_root / "bin" / "node",
        "#!/bin/sh\nprintf 'bound-node:%s\\n' \"$*\"\n",
    )
    return node_root


def create_fake_pnpm(tmp_path: Path) -> Path:
    pnpm = tmp_path / "pnpm"
    make_executable(
        pnpm,
        r"""#!/usr/bin/env python3
import json
import pathlib
import sys

directory = pathlib.Path(sys.argv[sys.argv.index("--dir") + 1])
requested = sys.argv[-1]
name, separator, version = requested.rpartition("@")
if not separator:
    name = requested
    version = "9.9.9"
(directory / "package.json").write_text(
    json.dumps({"private": True, "dependencies": {name: version}}),
    encoding="utf-8",
)
package = directory / "node_modules" / name
package.mkdir(parents=True)
(package / "package.json").write_text(
    json.dumps({"name": name, "version": version, "bin": {name: "cli.js"}}),
    encoding="utf-8",
)
executable = directory / "node_modules" / ".bin" / name
executable.parent.mkdir(parents=True)
executable.write_text('#!/bin/sh\nexec node --from-tool "$@"\n', encoding="utf-8")
executable.chmod(0o755)
""",
    )
    return pnpm


def test_install_creates_an_isolated_node_bound_launcher(tmp_path: Path) -> None:
    root = tmp_path / "tools"
    node_root = create_fake_node(tmp_path)
    pnpm = create_fake_pnpm(tmp_path)

    installed = node_tool.install_tool(
        "prettier@3.9.9",
        node_root=node_root,
        pnpm_path=pnpm,
        root=root,
    )

    assert installed == ("prettier", "3.9.9", ("prettier",))
    assert stat.S_IMODE((root / "envs" / "prettier").stat().st_mode) == 0o755
    launcher = root / "bin" / "prettier"
    result = subprocess.run(
        [str(launcher), "--version"],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.stdout == "bound-node:--from-tool --version\n"
    assert (root / "envs" / "prettier" / "node_modules" / "prettier" / "package.json").is_file()


def test_install_refuses_to_overwrite_an_existing_command(tmp_path: Path) -> None:
    root = tmp_path / "tools"
    node_root = create_fake_node(tmp_path)
    pnpm = create_fake_pnpm(tmp_path)
    make_executable(root / "bin" / "prettier", "#!/bin/sh\nexit 0\n")

    with pytest.raises(node_tool.NodeToolError, match="cannot expose executable"):
        node_tool.install_tool(
            "prettier@3.9.9",
            node_root=node_root,
            pnpm_path=pnpm,
            root=root,
        )

    assert not (root / "envs" / "prettier").exists()
