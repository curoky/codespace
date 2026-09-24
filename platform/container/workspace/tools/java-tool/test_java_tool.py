from __future__ import annotations

import importlib.util
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import pytest


def load_java_tool() -> ModuleType:
    source = Path(__file__).with_name("java-tool.py")
    spec = importlib.util.spec_from_file_location("java_tool", source)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


java_tool = load_java_tool()


def make_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def create_fake_java(tmp_path: Path) -> Path:
    java_root = tmp_path / "java"
    make_executable(
        java_root / "bin" / "java",
        '#!/bin/sh\nprintf \'java-home:%s\\nargs:%s\\n\' "$JAVA_HOME" "$*"\n',
    )
    return java_root


def create_tar_distribution(tmp_path: Path) -> Path:
    distribution = tmp_path / "archive-tool-1.2.3"
    make_executable(
        distribution / "bin" / "archive-tool",
        '#!/bin/sh\nprintf \'java-home:%s\\nargs:%s\\n\' "$JAVA_HOME" "$*"\n',
    )
    archive = tmp_path / "archive-tool.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        output.add(distribution, arcname=distribution.name)
    return archive


def create_jar(tmp_path: Path) -> Path:
    jar = tmp_path / "language-server.jar"
    with zipfile.ZipFile(jar, "w") as output:
        output.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n\r\n")
    jar.chmod(0o600)
    return jar


def test_install_archive_creates_launcher_bound_to_java(tmp_path: Path) -> None:
    root = tmp_path / "tools"
    java_root = create_fake_java(tmp_path)

    commands = java_tool.install_tool(
        "archive-tool@1.2.3",
        create_tar_distribution(tmp_path),
        java_root=java_root,
        root=root,
        extract=True,
        executables=("archive-tool=bin/archive-tool",),
        jars=(),
        executable_dirs=(),
    )

    assert stat.S_IMODE((root / "envs" / "archive-tool").stat().st_mode) == 0o755
    result = subprocess.run(
        [str(root / "bin" / "archive-tool"), "--version"],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert commands == ("archive-tool",)
    assert result.stdout == f"java-home:{java_root}\nargs:--version\n"


def test_install_jar_creates_java_jar_launcher(tmp_path: Path) -> None:
    root = tmp_path / "tools"
    java_root = create_fake_java(tmp_path)

    commands = java_tool.install_tool(
        "language-server@4.5.6",
        create_jar(tmp_path),
        java_root=java_root,
        root=root,
        extract=False,
        executables=(),
        jars=("language-server=language-server.jar",),
        executable_dirs=(),
    )

    installed_jar = root / "envs" / "language-server" / "payload" / "language-server.jar"
    assert stat.S_IMODE(installed_jar.stat().st_mode) == 0o644
    result = subprocess.run(
        [str(root / "bin" / "language-server"), "--stdio"],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert commands == ("language-server",)
    assert result.stdout == f"java-home:{java_root}\nargs:-jar {installed_jar} --stdio\n"


def test_install_exposes_executable_directory(tmp_path: Path) -> None:
    distribution = tmp_path / "suite-7.8.9"
    make_executable(
        distribution / "support" / "analyze",
        "#!/bin/sh\nprintf 'analyze:%s\\n' \"$*\"\n",
    )
    (distribution / "support" / "notes.txt").write_text("not executable", encoding="utf-8")
    archive = tmp_path / "suite.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for path in distribution.rglob("*"):
            output.write(path, path.relative_to(tmp_path))

    root = tmp_path / "tools"
    commands = java_tool.install_tool(
        "suite@7.8.9",
        archive,
        java_root=create_fake_java(tmp_path),
        root=root,
        extract=True,
        executables=(),
        jars=(),
        executable_dirs=("suite-=support",),
    )

    result = subprocess.run(
        [str(root / "bin" / "suite-analyze"), "project"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert commands == ("suite-analyze",)
    assert result.stdout == "analyze:project\n"


def test_install_rejects_archive_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape", b"bad")

    with pytest.raises(java_tool.JavaToolError, match="inside the distribution"):
        java_tool.install_tool(
            "unsafe@1.0",
            archive,
            java_root=create_fake_java(tmp_path),
            root=tmp_path / "tools",
            extract=True,
            executables=("unsafe=bin/unsafe",),
            jars=(),
            executable_dirs=(),
        )

    assert not (tmp_path / "escape").exists()


def test_install_does_not_overwrite_launcher(tmp_path: Path) -> None:
    root = tmp_path / "tools"
    make_executable(root / "bin" / "language-server", "#!/bin/sh\nexit 0\n")

    with pytest.raises(java_tool.JavaToolError, match="launcher already exists"):
        java_tool.install_tool(
            "language-server@4.5.6",
            create_jar(tmp_path),
            java_root=create_fake_java(tmp_path),
            root=root,
            extract=False,
            executables=(),
            jars=("language-server=language-server.jar",),
            executable_dirs=(),
        )

    assert not (root / "envs" / "language-server").exists()
