#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "typer==0.27.2",
# ]
# ///

from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Annotated, Literal

import typer

DEFAULT_JAVA = Path("/opt/java/openjdk27")
DEFAULT_ROOT = Path("/opt/java/tools")
NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Install Java CLI distributions bound to an explicit Java runtime.",
)


class JavaToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class Launcher:
    command: str
    kind: Literal["executable", "jar"]
    relative_path: PurePosixPath


def parse_package(value: str) -> tuple[str, str]:
    package, separator, version = value.rpartition("@")
    if not separator or not NAME_PATTERN.fullmatch(package) or not version:
        raise JavaToolError("package must be NAME@VERSION")
    return package, version


def relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or path == PurePosixPath(".") or ".." in path.parts:
        raise JavaToolError(f"path must stay inside the distribution: {value!r}")
    return path


def extract_zip(source: Path, destination: Path) -> None:
    try:
        with zipfile.ZipFile(source) as archive:
            for member in archive.infolist():
                path = relative_path(member.filename)
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise JavaToolError(f"archive contains a symbolic link: {member.filename!r}")
                target = destination.joinpath(*path.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as input_file, target.open("wb") as output_file:
                    shutil.copyfileobj(input_file, output_file)
                target.chmod(mode & 0o777 or 0o644)
    except zipfile.BadZipFile as error:
        raise JavaToolError(f"invalid ZIP archive: {source}") from error


def extract_tar(source: Path, destination: Path) -> None:
    try:
        with tarfile.open(source, "r:*") as archive:
            for member in archive.getmembers():
                relative_path(member.name)
                if not member.isfile() and not member.isdir():
                    raise JavaToolError(f"archive contains an unsupported entry: {member.name!r}")
            archive.extractall(destination, filter="data")
    except tarfile.TarError as error:
        raise JavaToolError(f"invalid TAR archive: {source}") from error


def prepare_payload(source: Path, destination: Path, *, extract: bool) -> Path:
    payload = destination / "payload"
    if not extract:
        payload.mkdir()
        installed = payload / source.name
        shutil.copy2(source, installed)
        installed.chmod(0o644)
        return payload

    unpacked = destination / "unpacked"
    unpacked.mkdir()
    if zipfile.is_zipfile(source):
        extract_zip(source, unpacked)
    elif tarfile.is_tarfile(source):
        extract_tar(source, unpacked)
    else:
        raise JavaToolError(f"source is not a ZIP or TAR archive: {source}")

    entries = list(unpacked.iterdir())
    if len(entries) != 1 or not entries[0].is_dir():
        raise JavaToolError("archive must contain one top-level directory")
    entries[0].replace(payload)
    return payload


def parse_launcher(value: str, kind: Literal["executable", "jar"]) -> Launcher:
    command, separator, target = value.partition("=")
    if not separator or not NAME_PATTERN.fullmatch(command):
        raise JavaToolError(f"launcher must be COMMAND=RELATIVE_PATH: {value!r}")
    return Launcher(command, kind, relative_path(target))


def launchers_for(
    payload: Path,
    *,
    executables: tuple[str, ...],
    jars: tuple[str, ...],
    executable_dirs: tuple[str, ...],
) -> tuple[Launcher, ...]:
    launchers = [parse_launcher(value, "executable") for value in executables]
    launchers.extend(parse_launcher(value, "jar") for value in jars)

    for value in executable_dirs:
        prefix, separator, directory_name = value.partition("=")
        if not separator or not NAME_PATTERN.fullmatch(prefix):
            raise JavaToolError(f"executable directory must be PREFIX=RELATIVE_PATH: {value!r}")
        directory = relative_path(directory_name)
        launchers.extend(
            Launcher(f"{prefix}{path.name}", "executable", directory / path.name)
            for path in sorted(payload.joinpath(*directory.parts).iterdir())
            if path.is_file() and os.access(path, os.X_OK)
        )

    if not launchers:
        raise JavaToolError("at least one launcher is required")
    if len({launcher.command for launcher in launchers}) != len(launchers):
        raise JavaToolError("launcher names must be unique")

    for launcher in launchers:
        target = payload.joinpath(*launcher.relative_path.parts)
        if not target.is_file():
            raise JavaToolError(f"launcher target does not exist: {target}")
        if launcher.kind == "executable" and not os.access(target, os.X_OK):
            raise JavaToolError(f"launcher target is not executable: {target}")
    return tuple(launchers)


def write_launcher(
    path: Path,
    *,
    java_root: Path,
    payload: Path,
    launcher: Launcher,
) -> None:
    target = payload.joinpath(*launcher.relative_path.parts)
    command = shlex.quote(str(target))
    if launcher.kind == "jar":
        command = f"{shlex.quote(str(java_root / 'bin' / 'java'))} -jar {command}"
    path.write_text(
        "\n".join(
            (
                "#!/bin/sh",
                f"JAVA_HOME={shlex.quote(str(java_root))}",
                f'PATH={shlex.quote(str(java_root / "bin"))}:"${{PATH:-/usr/bin:/bin}}"',
                "export JAVA_HOME PATH",
                f'exec {command} "$@"',
                "",
            )
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)


def install_tool(
    requested: str,
    source: Path,
    *,
    java_root: Path,
    root: Path,
    extract: bool,
    executables: tuple[str, ...],
    jars: tuple[str, ...],
    executable_dirs: tuple[str, ...],
) -> tuple[str, ...]:
    package, _ = parse_package(requested)
    source = source.resolve(strict=True)
    java_root = java_root.resolve(strict=True)
    root = root.resolve()
    if not source.is_file():
        raise JavaToolError(f"source is not a file: {source}")
    if not os.access(java_root / "bin" / "java", os.X_OK):
        raise JavaToolError(f"Java executable not found under: {java_root}")

    environments = root / "envs"
    target = environments / package
    if target.exists():
        raise JavaToolError(f"package is already installed: {package}")
    environments.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f".{package}-", dir=environments) as temporary:
        temporary_path = Path(temporary)
        payload = prepare_payload(source, temporary_path, extract=extract)
        launchers = launchers_for(
            payload,
            executables=executables,
            jars=jars,
            executable_dirs=executable_dirs,
        )
        bin_dir = root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        collisions = [
            launcher.command for launcher in launchers if (bin_dir / launcher.command).exists()
        ]
        if collisions:
            raise JavaToolError(f"launcher already exists: {', '.join(collisions)}")

        temporary_path.chmod(0o755)
        temporary_path.replace(target)
        for launcher in launchers:
            write_launcher(
                bin_dir / launcher.command,
                java_root=java_root,
                payload=target / "payload",
                launcher=launcher,
            )

    return tuple(launcher.command for launcher in launchers)


@app.callback()
def main() -> None:
    """Install Java tools from explicitly supplied release artifacts."""


@app.command()
def install(
    package: Annotated[str, typer.Argument(help="package as NAME@VERSION")],
    source: Annotated[Path, typer.Argument(help="release archive or JAR")],
    java: Annotated[Path, typer.Option("--java", help="Java installation root")] = DEFAULT_JAVA,
    root: Annotated[Path, typer.Option("--root", help="tool installation root")] = DEFAULT_ROOT,
    extract: Annotated[bool, typer.Option("--extract", help="extract a ZIP or TAR source")] = False,
    executable: Annotated[
        list[str] | None,
        typer.Option("--executable", help="COMMAND=RELATIVE_PATH"),
    ] = None,
    jar: Annotated[
        list[str] | None,
        typer.Option("--jar", help="COMMAND=RELATIVE_JAR_PATH"),
    ] = None,
    executable_dir: Annotated[
        list[str] | None,
        typer.Option("--executable-dir", help="PREFIX=RELATIVE_DIRECTORY"),
    ] = None,
) -> None:
    """Install one distribution and create its launchers."""
    try:
        commands = install_tool(
            package,
            source,
            java_root=java,
            root=root,
            extract=extract,
            executables=tuple(executable or ()),
            jars=tuple(jar or ()),
            executable_dirs=tuple(executable_dir or ()),
        )
    except (JavaToolError, OSError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"installed {package}: {', '.join(commands)}")


if __name__ == "__main__":
    app()
