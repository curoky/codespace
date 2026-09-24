#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "typer==0.27.2",
# ]
# ///

from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, cast
from urllib.parse import quote

import typer

DEFAULT_NODE = Path("/opt/node/nodejs24")
DEFAULT_PNPM = Path("/opt/node/tools/bin/pnpm")
DEFAULT_ROOT = Path("/opt/node/tools")

app = typer.Typer(add_completion=False, no_args_is_help=True)


class NodeToolError(RuntimeError):
    pass


def resolve_executable(path: Path, name: str) -> Path:
    try:
        executable = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise NodeToolError(f"{name} executable not found: {path}") from error
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise NodeToolError(f"{name} executable is not executable: {path}")
    return executable


def run_pnpm(command: list[str], node_bin: Path) -> None:
    environment = os.environ.copy()
    environment["PATH"] = f"{node_bin}:{environment.get('PATH', '/usr/bin:/bin')}"
    environment["CI"] = "true"
    environment["NO_UPDATE_NOTIFIER"] = "1"
    try:
        subprocess.run(command, check=True, env=environment)  # noqa: S603
    except subprocess.CalledProcessError as error:
        raise NodeToolError(f"pnpm failed with exit code {error.returncode}") from error


def read_json(path: Path) -> dict[str, object]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NodeToolError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise NodeToolError(f"expected a JSON object in {path}")
    return cast(dict[str, object], value)


def installed_package(environment: Path) -> tuple[str, str, tuple[str, ...]]:
    project = read_json(environment / "package.json")
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, dict) or len(dependencies) != 1:
        raise NodeToolError("pnpm did not install exactly one dependency")
    package = next(iter(dependencies))
    if not isinstance(package, str):
        raise NodeToolError("pnpm wrote an invalid dependency name")

    manifest = read_json(environment / "node_modules" / package / "package.json")
    version = manifest.get("version")
    package_bins = manifest.get("bin")
    if not isinstance(version, str):
        raise NodeToolError(f"{package} has no valid version")
    if isinstance(package_bins, str):
        bins: tuple[str, ...] = (package.rsplit("/", maxsplit=1)[-1],)
    elif isinstance(package_bins, dict):
        bins = tuple(sorted(name for name in package_bins if isinstance(name, str)))
    else:
        raise NodeToolError(f"{package} does not expose any executables")
    if not bins:
        raise NodeToolError(f"{package} does not expose any executables")
    return package, version, bins


def write_launcher(path: Path, node_bin: Path, executable: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                f'PATH={shlex.quote(str(node_bin))}:"${{PATH:-/usr/bin:/bin}}"',
                "export PATH",
                f'exec {shlex.quote(str(executable))} "$@"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)


def install_tool(
    requested: str,
    *,
    node_root: Path,
    pnpm_path: Path,
    root: Path,
) -> tuple[str, str, tuple[str, ...]]:
    node = resolve_executable(node_root / "bin" / "node", "Node.js")
    pnpm = resolve_executable(pnpm_path, "pnpm")
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "store").mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".node-tool-", dir=root) as temporary_name:
        temporary = Path(temporary_name)
        (temporary / "package.json").write_text('{"private":true}\n', encoding="utf-8")
        run_pnpm(
            [
                str(pnpm),
                "--dir",
                str(temporary),
                "--store-dir",
                str(root / "store"),
                "add",
                "--save-exact",
                requested,
            ],
            node.parent,
        )
        package, version, bins = installed_package(temporary)
        environment = root / "envs" / quote(package, safe="")
        if environment.exists():
            raise NodeToolError(f"{package} is already installed")

        bin_dir = root / "bin"
        bin_dir.mkdir(exist_ok=True)
        for name in bins:
            if Path(name).name != name or (bin_dir / name).exists():
                raise NodeToolError(f"cannot expose executable: {name}")
            if not (temporary / "node_modules" / ".bin" / name).is_file():
                raise NodeToolError(f"pnpm did not install executable: {name}")

        environment.parent.mkdir(exist_ok=True)
        temporary.replace(environment)
        for name in bins:
            write_launcher(
                bin_dir / name,
                node.parent,
                environment / "node_modules" / ".bin" / name,
            )
    return package, version, bins


@app.callback()
def main() -> None:
    """Install isolated Node.js CLI packages bound to an explicit Node.js runtime."""


@app.command()
def install(
    package: Annotated[str, typer.Argument(help="npm package with an optional version or tag")],
    node: Annotated[
        Path,
        typer.Option("--node", help="Root of the Node.js installation"),
    ] = DEFAULT_NODE,
    pnpm: Annotated[
        Path,
        typer.Option("--pnpm", help="Path to the pnpm executable"),
    ] = DEFAULT_PNPM,
    root: Annotated[
        Path,
        typer.Option("--root", help="Root for isolated environments and launchers"),
    ] = DEFAULT_ROOT,
) -> None:
    """Install one npm CLI package."""
    try:
        name, version, bins = install_tool(
            package,
            node_root=node,
            pnpm_path=pnpm,
            root=root,
        )
    except NodeToolError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"installed {name}@{version}: {', '.join(bins)}")


if __name__ == "__main__":
    app()
