"""Behavior checks for executable container entrypoints."""

# ruff: noqa: S104, S603, S607

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

_CONTAINER = Path(__file__).resolve().parents[1] / "platform/container"


def _s6_longrun_directories() -> list[Path]:
    return sorted(
        path.parent
        for path in _CONTAINER.glob("**/rootfs/etc/s6/s6-rc.d/*/type")
        if path.read_text().strip() == "longrun"
    )


def _s6_service_entrypoints() -> list[Path]:
    entrypoints = [
        _CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d/atuin-server/run",
        _CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d/miniserve-logs/run",
        _CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d/ollama/run",
        _CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d/supercronic/run",
        _CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d/workspace-agent/run",
    ]
    for dockerfile in (_CONTAINER / "services").glob("*/Dockerfile"):
        base_images = [
            line.split()[1]
            for line in dockerfile.read_text().splitlines()
            if line.startswith("FROM ")
        ]
        if base_images[-1] != "ghcr.io/curoky/codespace:service-s6":
            continue
        service_files = dockerfile.parent.glob("rootfs/etc/s6/s6-rc.d/*/*")
        entrypoints.extend(path for path in service_files if path.name in {"run", "up"})
    return sorted(entrypoints)


def test_workspace_secret_mount_uses_default_network_dns() -> None:
    helper = _CONTAINER / "workspace/rootfs/opt/codespace/bin/mount-secret"

    assert 'local url="http://codespace-service-secret:8080"' in helper.read_text()


def test_workspace_atuin_uses_official_sync_service_with_secret_login() -> None:
    workspace = _CONTAINER / "workspace"
    config = (workspace / "rootfs/home/x/.config/atuin/config.toml").read_text()
    services = workspace / "rootfs/etc/s6/s6-rc.d"
    login = (services / "atuin-login/up").read_text()

    assert 'sync_address = "https://api.atuin.sh"' in config
    assert (services / "atuin-server/run").exists()
    assert (services / "atuin-login/up").exists()
    assert (services / "default/contents.d/atuin-login").exists()
    assert not (services / "default/contents.d/atuin-server").exists()
    assert (services / "atuin-daemon/dependencies.d/atuin-login").exists()
    assert not (services / "atuin-login/dependencies.d/atuin-server").exists()
    assert login.count("/run/secrets/atuin_credentials") == 4
    assert "/usr/bin/cut -s -d / -f 1" in login
    assert "/usr/bin/cut -s -d / -f 2" in login
    assert "/usr/bin/cut -s -d / -f 3-" in login
    assert "--username ${ATUIN_USERNAME}" in login
    assert "--password ${ATUIN_PASSWORD}" in login
    assert "--key ${ATUIN_KEY}" in login


def test_workspace_gh_login_defaults_to_public_read_token() -> None:
    workspace = _CONTAINER / "workspace"
    login = (workspace / "rootfs/etc/s6/s6-rc.d/gh-login/up").read_text()
    github_skill = (workspace / "rootfs/home/x/.codex/skills/debug-github/SKILL.md").read_text()

    public_token = "/run/secrets/github_token_public_read"
    actions_token = "/run/secrets/github_token_all_action_rw"
    assert login.count(public_token) == 2
    assert actions_token not in login
    assert f'GH_TOKEN="$(cat {actions_token})"' in github_skill


def test_workspace_agents_share_codex_skills() -> None:
    home = _CONTAINER / "workspace/rootfs/home/x"

    for skill in ("debug-github", "manage-services"):
        target = f"../../.codex/skills/{skill}"
        assert (home / ".trae/skills" / skill).readlink() == Path(target)
        assert (home / ".trae-cn/skills" / skill).readlink() == Path(target)


def test_app_profile_sets_tools_and_preserves_inherited_environment(tmp_path: Path) -> None:
    profile = _CONTAINER / "workspace/rootfs/etc/profile.d/app.sh"
    inherited = {
        "LANG": "C",
        "LC_ALL": "C",
        "LANGUAGE": "C",
        "XDG_CACHE_HOME": "/project/cache",
        "XDG_CONFIG_HOME": "/project/config",
        "XDG_DATA_HOME": "/project/data",
        "XDG_RUNTIME_DIR": "/project/runtime",
        "TMPDIR": "/project/tmp",
        "http_proxy": "http://project-proxy:3128",
        "HTTP_PROXY": "http://project-proxy:3128",
        "no_proxy": "project.internal",
        "NO_PROXY": "project.internal",
    }
    result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            '. "$1"; . "$1"; env -0',
            "profile-test",
            str(profile),
        ],
        env={
            **inherited,
            "HOME": str(tmp_path),
            "PATH": "/project/venv/bin:/usr/bin:/bin",
            "JAVA_HOME": "/project/jdk",
            "CARGO_HOME": "/project/cargo",
            "RUSTUP_HOME": "/project/rustup",
            "CUDA_HOME": "/project/cuda",
            "LD_LIBRARY_PATH": "/project/lib",
        },
        capture_output=True,
        text=True,
        check=True,
    )
    environment = dict(item.split("=", 1) for item in result.stdout.split("\0") if item)
    assert {key: environment[key] for key in inherited} == inherited
    entries = environment["PATH"].split(":")
    assert entries[0] == "/project/venv/bin"
    assert len(entries) == len(set(entries))
    assert {"/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/sbin"}.isdisjoint(entries)
    assert {
        "/usr/local/profile/go/bin",
        "/usr/local/profile/clang-tools/bin",
        "/usr/local/profile/protobuf/bin",
        "/home/x/go/bin",
        "/home/x/.local/share/pnpm/bin",
        "/opt/java/java-tool",
        "/opt/java/openjdk27/bin",
        "/opt/node/node-tool",
    }.issubset(entries)
    assert environment["JAVA_HOME"] == "/opt/java/openjdk27"
    assert environment["CARGO_HOME"] == "/home/x/.cargo"
    assert environment["RUSTUP_HOME"] == "/opt/rust/rustup"
    assert environment["LD_LIBRARY_PATH"] == "/usr/local/cuda/lib64"


def test_workspace_hosts_blackhole_runs_as_root_without_sudo() -> None:
    helper = _CONTAINER / "workspace/rootfs/opt/codespace/bin/init-hosts-blackhole"
    service = _CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d/hosts-blackhole/up"

    assert "sudo" not in helper.read_text()
    assert "s6-setuidgid" not in service.read_text()


def test_workspace_root_services_use_only_root_owned_path() -> None:
    init = (_CONTAINER / "workspace/rootfs/etc/s6/skel/rc.init").read_text()

    root_path = "/usr/local/bin:/usr/local/sbin:/usr/local/libexec:/usr/bin:/usr/sbin:/bin:/sbin"
    assert f'export PATH="{root_path}"' in init
    assert "rm -f /run/s6/container_environment/PATH" in init
    assert "chgrp" not in init
    assert "chmod 0640" not in init


def test_workspace_root_password_tools_support_system_authentication() -> None:
    configure = (_CONTAINER / "workspace/scripts/configure-system.sh").read_text()
    password_init = (
        _CONTAINER / "workspace/rootfs/opt/codespace/bin/init-root-password"
    ).read_text()
    sudoers = (_CONTAINER / "workspace/rootfs/etc/sudoers").read_text()

    assert "rm -f /usr/local/bin/su /usr/local/sbin/su" in configure
    assert "/usr/sbin/chpasswd --crypt-method SHA512" in password_init
    assert "x ALL=(ALL:ALL) ALL" in sudoers


def test_workspace_gocryptfs_uses_workspace_identity() -> None:
    workspace = _CONTAINER / "workspace"
    configure = (workspace / "scripts/configure-system.sh").read_text()
    service = (workspace / "rootfs/etc/s6/s6-rc.d/gocryptfs-workspace/run").read_text()
    config = yaml.safe_load(Path("config.example.yaml").read_text())
    workspace_key = next(
        secret
        for secret in config["project_defaults"]["container"]["secrets"]
        if secret["source"] == "codespace_workspace_key"
    )

    assert "user-group --shell /usr/sbin/nologin gocryptfs" not in configure
    assert workspace_key == {
        "source": "codespace_workspace_key",
        "uid": "5230",
        "gid": "5230",
        "mode": 0o400,
    }
    assert "install -d -o 5230 -g 5230 -m 0700 -- /workspace /workspace.enc" in service
    assert 's6-applyuidgid -u 5230 -g 5230 -G ""' in service
    assert "s6-setuidgid x" in service
    assert "-allow_other" in service
    assert "-force_owner" not in service


def test_workspace_image_packages_are_root_owned_and_user_installs_use_local() -> None:
    dockerfile = (_CONTAINER / "workspace/Dockerfile").read_text()
    manifest = (_CONTAINER / "workspace/config/binman.yaml").read_text()

    assert "prefix: /usr/local" in manifest
    assert "binman-root" not in dockerfile
    assert "--from=stage_sb /opt/bm" not in dockerfile
    assert not (_CONTAINER / "workspace/rootfs/home/x/.local/bin/bm").exists()
    assert (
        "/home/x/.local/bin" in (_CONTAINER / "workspace/rootfs/etc/profile.d/app.sh").read_text()
    )
    assert "- podman5-rootless" in manifest
    assert "bm download" not in dockerfile


def test_workspace_bundles_runtimes_and_keeps_java_tools_in_resource() -> None:
    workspace = _CONTAINER / "workspace"
    workspace_dockerfile = (workspace / "Dockerfile").read_text()
    resource_dockerfile = (workspace / "resource.Dockerfile").read_text()
    profile = (_CONTAINER / "workspace/rootfs/etc/profile.d/app.sh").read_text()
    settings = yaml.safe_load(
        (workspace / "rootfs/home/x/.vscode-server/data/Machine/settings.json").read_text()
    )
    rootfs_opt = workspace / "rootfs/opt"
    expected_links = {
        "nvidia/nsight-compute": Path("/opt/resource/opt/nvidia/nsight-compute"),
        "nvidia/nsight-systems-cli": Path("/opt/resource/opt/nvidia/nsight-systems-cli"),
    }
    actual_links = {
        str(path.relative_to(rootfs_opt)): path.readlink()
        for family in (rootfs_opt / "java", rootfs_opt / "node", rootfs_opt / "nvidia")
        for path in family.rglob("*")
        if path.is_symlink()
    }

    assert "/opt/java/tools/bin" in profile
    assert "/opt/resource/opt/java/tools/bin" in profile
    assert "/opt/node/tools/bin" in profile
    assert "/opt/resource/opt/node" not in profile
    for family in ("go", "node", "rust", "java"):
        assert (
            f"COPY --link --chown=5230:5230 --from=stage_{family} /opt/{family} /opt/{family}"
            in workspace_dockerfile
        )
        assert not (rootfs_opt / family).is_symlink()
    assert "--java /opt/java/openjdk27" in resource_dockerfile
    assert "--node /opt/node/nodejs24" in workspace_dockerfile
    assert "--pnpm /usr/local/bin/pnpm" in workspace_dockerfile
    assert (
        "COPY --from=stage_java /opt/java/tools /opt/resource/opt/java/tools" in resource_dockerfile
    )
    for family in ("go", "node", "rust"):
        assert f"COPY --from=stage_{family}" not in resource_dockerfile
    assert "FROM payload AS test" in resource_dockerfile
    assert "FROM test AS resource" in resource_dockerfile
    assert settings["prettier.prettierPath"].startswith("/opt/node/tools/")
    assert settings["xml.server.binary.path"] == "/opt/resource/opt/java/tools/bin/lemminx"
    assert actual_links == expected_links


def test_workspace_keeps_required_python_and_bundles_python_tools() -> None:
    workspace = _CONTAINER / "workspace"
    dockerfile = (workspace / "Dockerfile").read_text()
    resource_dockerfile = (workspace / "resource.Dockerfile").read_text()
    profile = (workspace / "rootfs/etc/profile.d/app.sh").read_text()
    assert "uv python install 3.14" in dockerfile
    runtime_stage = dockerfile.split("FROM docker.io/$BASE_IMAGE AS workspace\n", 1)[1]
    assert not any(line.startswith("ENV ") for line in runtime_stage.splitlines())
    assert "COPY --link --chown=5230:5230 --from=stage_python /opt/uv /opt/uv" in runtime_stage
    assert '"$UV_PYTHON_BIN_DIR"' in profile
    assert "--python /opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14" in dockerfile
    assert "uv tool install copyparty" in dockerfile
    assert "uv tool install copyparty" not in resource_dockerfile

    python_install = re.search(r"uv python install --no-bin ([^\n]+)", resource_dockerfile)
    assert python_install is not None
    python_versions = python_install.group(1).removesuffix("\\").split()
    assert "FROM ghcr.io/astral-sh/uv:" not in resource_dockerfile
    assert (
        "COPY --from=stage_build_tools /usr/local/store/uv/bin/uv /usr/local/bin/uv"
        in resource_dockerfile
    )
    for tool in ("licenseheaders", "netron", "mitmproxy", "dool", "git-filter-repo"):
        assert f"uv tool install {tool}" in dockerfile
        assert f"uv tool install {tool}" not in resource_dockerfile
    resource_tools = {"tensorboard": "3.12.15"}
    for tool, python in resource_tools.items():
        minor = ".".join(python.split(".")[:2])
        assert f"uv tool install {tool}" in resource_dockerfile
        assert (
            f"--python /opt/resource/opt/uv/python/cpython-{python}-linux-x86_64-gnu/"
            f"bin/python{minor}" in resource_dockerfile
        )
        assert f"uv tool install {tool}" not in dockerfile
    assert "/opt/resource/opt/uv/bin" in profile
    python_root = workspace / "rootfs/opt/uv/python"
    installations = {path.name: path for path in python_root.iterdir() if not path.is_symlink()}
    aliases = {path.name: path.readlink() for path in python_root.iterdir() if path.is_symlink()}
    assert set(installations) == {
        f"cpython-{version}-linux-x86_64-gnu" for version in python_versions if version != "3.14"
    }
    assert aliases == {
        f"cpython-{'.'.join(version.split('.')[:2])}-linux-x86_64-gnu": Path(
            f"cpython-{version}-linux-x86_64-gnu"
        )
        for version in python_versions
        if version != "3.14"
    }
    for installation in installations.values():
        assert installation.is_dir() and not installation.is_symlink()
        assert {path.name for path in installation.iterdir()} == {
            "BUILD",
            "bin",
            "include",
            "lib",
            "share",
        }
        for child in installation.iterdir():
            assert (
                child.readlink()
                == Path("/opt/resource/opt/uv/python") / installation.name / child.name
            )


@pytest.mark.skipif(
    sys.platform != "linux" or os.uname().machine != "x86_64",
    reason="Workspace Python installations target Linux x86_64",
)
def test_uv_discovers_linked_python_and_creates_a_venv(tmp_path: Path) -> None:
    version = ".".join(str(part) for part in sys.version_info[:3])
    minor = ".".join(str(part) for part in sys.version_info[:2])
    python_root = tmp_path / "python"
    installation = python_root / f"cpython-{version}-linux-x86_64-gnu"
    installation.mkdir(parents=True)
    alias = python_root / f"cpython-{minor}-linux-x86_64-gnu"
    alias.symlink_to(installation.name)
    declarations = _CONTAINER / "workspace/rootfs/opt/uv/python"
    for child in next(path for path in declarations.iterdir() if not path.is_symlink()).iterdir():
        (installation / child.name).symlink_to(Path(sys.base_prefix) / child.name)
    environment = {**os.environ, "UV_PYTHON_INSTALL_DIR": str(python_root)}
    environment.pop("VIRTUAL_ENV", None)
    for requested in (minor, version):
        result = subprocess.run(
            [
                "uv",
                "python",
                "find",
                "--no-project",
                "--no-config",
                "--managed-python",
                "--offline",
                "--no-python-downloads",
                requested,
            ],
            env=environment,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert Path(result.stdout.strip()) == installation / "bin" / f"python{minor}"
    venv = tmp_path / "venv"
    subprocess.run(
        [
            "uv",
            "venv",
            "--managed-python",
            "--offline",
            "--no-python-downloads",
            "--python",
            version,
            str(venv),
        ],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    result = subprocess.run(
        [
            str(venv / "bin/python"),
            "-c",
            "import ssl, ctypes, json, sys; print(sys.version.split()[0])",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == version
    alias_venv = tmp_path / "alias-venv"
    subprocess.run(
        [
            "uv",
            "venv",
            "--managed-python",
            "--offline",
            "--no-python-downloads",
            "--python",
            str(alias / "bin" / f"python{minor}"),
            str(alias_venv),
        ],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert (alias_venv / "bin/python").readlink() == alias / "bin" / f"python{minor}"
    assert f"home = {alias / 'bin'}" in (alias_venv / "pyvenv.cfg").read_text()
    result = subprocess.run(
        [
            str(alias_venv / "bin/python"),
            "-c",
            "import ssl, ctypes, json, sys; print(sys.version.split()[0])",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == version


def test_workspace_bundles_java_and_node_installers() -> None:
    workspace = _CONTAINER / "workspace"
    dockerfile = (workspace / "Dockerfile").read_text()
    profile = (workspace / "rootfs/etc/profile.d/app.sh").read_text()
    node_tool = (workspace / "tools/node-tool/node-tool").read_text()
    java_tool = (workspace / "tools/java-tool/java-tool").read_text()

    assert (
        "COPY --chown=5230:5230 platform/container/workspace/tools/node-tool/ /opt/node/node-tool/"
        in dockerfile
    )
    assert (
        "COPY --chown=5230:5230 platform/container/workspace/tools/java-tool/ /opt/java/java-tool/"
        in dockerfile
    )
    resource_dockerfile = (workspace / "resource.Dockerfile").read_text()
    assert "COPY platform/container/workspace/tools/node-tool/ /tmp/node-tool/" in dockerfile
    assert "/tmp/node-tool/node-tool init" in dockerfile
    assert "node-tool" not in resource_dockerfile
    assert "uv run --locked --script /tmp/node-tool/node-tool.py" not in dockerfile
    assert (
        "COPY platform/container/workspace/tools/java-tool/ /tmp/java-tool/" in resource_dockerfile
    )
    assert "/tmp/java-tool/java-tool init" in resource_dockerfile
    assert "uv run --locked --script /tmp/java-tool/java-tool.py" not in resource_dockerfile
    assert "/opt/node/node-tool/node-tool init" in dockerfile
    assert "/opt/java/java-tool/java-tool init" in dockerfile
    for name, wrapper in (("node-tool", node_tool), ("java-tool", java_tool)):
        tool = workspace / "tools" / name
        project = tomllib.loads((tool / "pyproject.toml").read_text())
        assert project["project"]["dependencies"] == ["typer==0.27.2"]
        assert project["tool"]["uv"]["package"] is False
        assert (tool / "uv.lock").is_file()
        assert not (tool / f"{name}.py.lock").exists()
        assert 'script_dir="$(dirname "$(readlink -f "$0")")"' in wrapper
        assert (
            '/usr/local/bin/uv sync --project "$script_dir" --locked --no-dev --python 3.14'
            in wrapper
        )
        assert f'exec "$script_dir/.venv/bin/python" "$script_dir/{name}.py" "$@"' in wrapper
    assert "/opt/java/java-tool" in profile
    assert "/opt/node/node-tool" in profile
    assert os.access(workspace / "tools/java-tool/java-tool", os.X_OK)
    assert os.access(workspace / "tools/node-tool/node-tool", os.X_OK)


@pytest.mark.parametrize("name", ["node-tool", "java-tool"])
def test_tool_wrapper_requires_init_and_reuses_its_environment(tmp_path: Path, name: str) -> None:
    tool = tmp_path / name
    tool.mkdir()
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "from pathlib import Path\n"
        "import sys\n"
        "environment = Path(os.environ['UV_PROJECT_ENVIRONMENT'])\n"
        "record = environment.parent / 'sync-calls'\n"
        "with record.open('a') as output:\n"
        "    output.write(repr((os.environ.get('VIRTUAL_ENV'), "
        "os.environ['UV_PYTHON_INSTALL_DIR'], sys.argv[1:])) + '\\n')\n"
        "binary = environment / 'bin' / 'python'\n"
        "binary.parent.mkdir(parents=True, exist_ok=True)\n"
        "binary.write_text('#!/usr/bin/env bash\\nprintf \\'%s\\\\n\\' \\\"$@\\\"\\n')\n"
        "binary.chmod(0o755)\n"
    )
    fake_uv.chmod(0o755)
    source = (_CONTAINER / "workspace/tools" / name / name).read_text()
    wrapper = tool / name
    wrapper.write_text(source.replace("/usr/local/bin/uv", str(fake_uv)))
    wrapper.chmod(0o755)
    environment = {
        "PATH": "/usr/bin:/bin",
        "VIRTUAL_ENV": str(tmp_path / "caller-venv"),
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / "caller-project"),
        "UV_PYTHON_INSTALL_DIR": str(tmp_path / "caller-python"),
    }
    for arguments in [[], ["--help"], ["install"]]:
        result = subprocess.run(
            [str(wrapper), *arguments],
            env=environment,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1
        assert result.stdout == ""
        assert f'run "{wrapper} init" first' in result.stderr
        assert not (tool / "sync-calls").exists()
        assert not (tool / ".venv").exists()

    result = subprocess.run(
        [str(wrapper), "init", "--python", "3.13"],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert f"usage: {wrapper} init" in result.stderr
    assert not (tool / "sync-calls").exists()

    init_arguments = [str(wrapper), "init"]
    result = subprocess.run(
        init_arguments,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""
    for argument in ["--help", "--version"]:
        result = subprocess.run(
            [str(wrapper), argument],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        assert result.stdout.splitlines() == [str(tool / f"{name}.py"), argument]
    calls = (tool / "sync-calls").read_text().splitlines()
    sync_arguments = ["sync", "--project", str(tool), "--locked", "--no-dev"]
    assert calls == [repr((None, "/opt/uv/python", [*sync_arguments, "--python", "3.14"]))]

    result = subprocess.run(
        init_arguments,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""
    result = subprocess.run(
        [str(wrapper), "--help"],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout.splitlines() == [str(tool / f"{name}.py"), "--help"]
    assert (tool / "sync-calls").read_text().splitlines() == [
        *calls,
        repr((None, "/opt/uv/python", [*sync_arguments, "--python", "3.14"])),
    ]
    assert not (tmp_path / "caller-project").exists()


def test_workspace_resource_image_installs_binman_manifest() -> None:
    workspace = _CONTAINER / "workspace"
    dockerfile = (workspace / "resource.Dockerfile").read_text()
    manifest = yaml.safe_load((workspace / "config/binman-resource.yaml").read_text())

    assert (
        "COPY platform/container/workspace/config/binman-resource.yaml /tmp/binman.yaml"
        in dockerfile
    )
    assert "/usr/local/bin/bm --prefix /usr/local install --file /tmp/binman.yaml" in dockerfile
    assert "/usr/local/bin/bm --prefix /usr/local install --no-link uv" in dockerfile
    assert "registry.npmjs.org/@pnpm" not in dockerfile
    assert "rm -f /usr/local/bin/bm" in dockerfile
    assert "COPY --from=stage_sb /usr/local/bin /opt/resource/usr/local/bin" in dockerfile
    assert "test ! -e /opt/resource/usr/local/bin/bm" in dockerfile
    assert "test ! -e /opt/resource/usr/local/bin/uv" in dockerfile
    assert "test ! -e /opt/resource/usr/local/bin/pnpm" in dockerfile
    assert "test ! -e /opt/resource/opt/uv/bin/uv" in dockerfile
    assert "test ! -e /opt/resource/usr/local/store/uv" in dockerfile
    assert "test ! -e /opt/resource/usr/local/store/pnpm" in dockerfile
    assert "test ! -e /opt/resource/opt/node" in dockerfile
    assert "COPY --from=stage_sb /usr/local/profile /opt/resource/usr/local/profile" in dockerfile
    assert "/opt/resource/usr/local/bin/radare2 -v" in dockerfile
    assert "/opt/resource/usr/local/bin/rizin -v" in dockerfile
    assert "/opt/resource/usr/local/bin" in (workspace / "rootfs/etc/profile.d/app.sh").read_text()
    assert not (workspace / "rootfs/usr/local/store/radare2").exists()
    assert not (workspace / "rootfs/usr/local/store/rizin").exists()

    profiles = {
        install["link-to"]: set(install["packages"])
        for install in manifest["installs"]
        if install.get("link-to", "").startswith("profile/")
    }
    assert profiles["profile/clang-tools"] == {
        "clang-tools-18",
        "clang-tools-19",
        "clang-tools-20",
        "clang-tools-21",
        "clang-tools-22",
        "clang-tools-23",
    }
    assert profiles["profile/protobuf"] == {
        "protobuf3_20",
        "protobuf3_21",
        "protobuf_23",
        "protobuf_24",
        "protobuf_25",
        "protobuf_26",
        "protobuf_27",
        "protobuf_28",
        "protobuf_29",
        "protobuf_3_8_0",
        "protobuf_3_9_2",
    }
    assert set(profiles) == {"profile/clang-tools", "profile/go", "profile/protobuf"}

    rootfs_profiles = workspace / "rootfs/usr/local/profile"
    for profile in ("clang-tools", "go", "protobuf"):
        assert (rootfs_profiles / profile).readlink() == Path(
            f"/opt/resource/usr/local/profile/{profile}"
        )


@pytest.mark.parametrize(
    ("manifest_path", "prefix"),
    [
        (_CONTAINER / "workspace/config/binman.yaml", "/usr/local"),
        (_CONTAINER / "workspace/config/binman-resource.yaml", "/usr/local"),
        (_CONTAINER / "services/s6/binman.yaml", "/usr/local"),
        (_CONTAINER.parent / "macos/binman.yaml", "/opt/bm"),
    ],
)
def test_binman_manifests_use_install_plan_schema(manifest_path: Path, prefix: str) -> None:
    manifest = yaml.safe_load(manifest_path.read_text())

    assert set(manifest) == {"prefix", "installs"}
    assert manifest["prefix"] == prefix
    assert manifest["installs"]
    for install in manifest["installs"]:
        assert set(install) <= {"packages", "link-to"}
        assert install["packages"]


def test_workspace_binman_manifests_do_not_overlap() -> None:
    workspace = yaml.safe_load((_CONTAINER / "workspace/config/binman.yaml").read_text())
    resource = yaml.safe_load((_CONTAINER / "workspace/config/binman-resource.yaml").read_text())

    workspace_packages = [
        package for install in workspace["installs"] for package in install["packages"]
    ]
    resource_packages = [
        package for install in resource["installs"] for package in install["packages"]
    ]

    assert len(workspace_packages) == len(set(workspace_packages))
    assert len(resource_packages) == len(set(resource_packages))
    assert set(workspace_packages).isdisjoint(resource_packages)


def test_container_binman_commands_use_current_cli_and_explicit_prefix() -> None:
    dockerfiles = sorted(_CONTAINER.glob("**/*Dockerfile"))

    for dockerfile in dockerfiles:
        contents = dockerfile.read_text()
        if "/usr/local/bin/bm" not in contents:
            continue
        assert "/usr/local/bin/bm sync" not in contents, dockerfile
        assert "/usr/local/bin/bm install" not in contents, dockerfile
        assert "/usr/local/bin/bm --prefix /usr/local install" in contents, dockerfile


def test_workspace_podman_separates_image_files_from_user_data() -> None:
    workspace = _CONTAINER / "workspace"
    server = (workspace / "rootfs/opt/podman/bin/podman-server").read_text()
    configure = (workspace / "scripts/configure-system.sh").read_text()
    dockerfile = (workspace / "Dockerfile").read_text()
    profile = (workspace / "rootfs/etc/profile.d/app.sh").read_text()
    run = (workspace / "rootfs/etc/s6/s6-rc.d/podman/run").read_text()
    finish = (workspace / "rootfs/etc/s6/s6-rc.d/podman/finish").read_text()

    assert "PODMAN_DATA_DIR=/opt/podman/data" in server
    assert "CONTAINERS_CONF=/etc/containers/containers.conf" in server
    assert "--network-config-dir=/opt/podman/network" in server
    assert "/opt/podman/conf" not in server
    assert "/opt/podman/bin" in profile
    assert "export BUILDAH_ISOLATION=chroot" in profile
    assert "export BUILDAH_ISOLATION=chroot" in server
    assert "exec /opt/podman/bin/podman-server" in run
    assert "exec /opt/podman/bin/podman-server --stop-all" in finish
    assert not (workspace / "rootfs/usr/local/bin/podman").exists()
    assert not (workspace / "rootfs/usr/local/bin/podman-server").exists()
    assert "chown" not in configure
    ownership = dockerfile.index("chown -hR 5230:5230 /home/x /opt/java /opt/node /opt/uv")
    assert (
        dockerfile.index("COPY platform/container/workspace/rootfs/ /")
        < ownership
        < dockerfile.index("COPY --link --from=stage_sb")
    )
    assert "/usr/local/libexec/codespace" not in configure


def test_workspace_podman_generates_nvidia_cdi_from_runtime_driver() -> None:
    workspace = _CONTAINER / "workspace"
    dockerfile = (workspace / "Dockerfile").read_text()
    generator = (workspace / "rootfs/opt/podman/bin/generate-nvidia-cdi").read_text()
    run = (workspace / "rootfs/etc/s6/s6-rc.d/podman/run").read_text()

    assert "nvidia-container-toolkit-base_1.20.1-1_amd64.deb" in dockerfile
    assert "--strip-components=3" in dockerfile
    assert "./usr/bin/nvidia-ctk" in dockerfile
    assert "./usr/bin/nvidia-cdi-hook" in dockerfile
    assert "/opt/nvidia-container-toolkit/" in dockerfile
    assert "/opt/nvidia/nvidia-container-toolkit/" in dockerfile
    assert "[[ ! -c /dev/nvidiactl ]]" in generator
    assert "/opt/nvidia/nvidia-container-toolkit/nvidia-ctk" in generator
    assert "cdi generate --output=/var/run/cdi/nvidia.yaml" in generator
    assert "foreground { /opt/podman/bin/generate-nvidia-cdi }" in run


def test_s6_services_do_not_load_shared_environment_directories() -> None:
    entrypoints = sorted(_CONTAINER.glob("**/rootfs/etc/s6/s6-rc.d/*/run"))
    entrypoints += sorted(_CONTAINER.glob("**/rootfs/etc/s6/s6-rc.d/*/up"))

    for entrypoint in entrypoints:
        run = entrypoint.read_text()
        assert "s6-envdir" not in run, entrypoint


def test_log_server_listener_is_configured_by_each_image() -> None:
    run = (_CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d/miniserve-logs/run").read_text()
    workspace = (_CONTAINER / "workspace/Dockerfile").read_text()
    service = (_CONTAINER / "services/s6/Dockerfile").read_text()

    assert (
        "backtick -D 127.0.0.1 MINISERVE_INTERFACES "
        "{ cat /run/s6/container_environment/MINISERVE_INTERFACES }"
    ) in run
    assert "--interfaces ${MINISERVE_INTERFACES}" in run
    assert "exec /usr/local/store/miniserve/bin/miniserve" in run
    assert "MINISERVE_INTERFACES" not in workspace
    assert "MINISERVE_INTERFACES=0.0.0.0" in service
    assert "prefix: /usr/local" in (_CONTAINER / "services/s6/binman.yaml").read_text()


def test_s6_services_use_store_paths_for_image_managed_binman_commands() -> None:
    command = re.compile(r"(?<![/\w-])(?:atuin|gh|miniserve|nixcache|rclone|supercronic)(?=\s)")
    entrypoints = sorted(_CONTAINER.glob("**/rootfs/etc/s6/s6-rc.d/*/run"))
    entrypoints += sorted(_CONTAINER.glob("**/rootfs/etc/s6/s6-rc.d/*/up"))

    for entrypoint in entrypoints:
        for line_number, line in enumerate(entrypoint.read_text().splitlines(), start=1):
            if line.lstrip().startswith("#"):
                continue
            assert command.search(line) is None, f"{entrypoint}:{line_number}: {line}"


@pytest.mark.parametrize("service", _s6_longrun_directories())
def test_s6_longrun_entrypoints_are_executable(service: Path) -> None:
    assert os.access(service / "run", os.X_OK)


@pytest.mark.parametrize(
    ("relative_service", "probe"),
    [
        ("workspace/rootfs/etc/s6/s6-rc.d/atuin-server", "127.0.0.1:8002/"),
        ("workspace/rootfs/etc/s6/s6-rc.d/sshd", "127.0.0.1 22"),
        ("services/chatbox/rootfs/etc/s6/s6-rc.d/nginx", "127.0.0.1:8080/healthz"),
        ("services/secret/rootfs/etc/s6/s6-rc.d/rclone-webdav", "127.0.0.1:8080/"),
        ("services/sglang/rootfs/etc/s6/s6-rc.d/serve", "127.0.0.1:8080/health"),
        ("services/vllm/rootfs/etc/s6/s6-rc.d/serve", "127.0.0.1:8080/health"),
    ],
)
def test_required_s6_services_publish_readiness(relative_service: str, probe: str) -> None:
    service = _CONTAINER / relative_service
    run = (service / "run").read_text()
    notify_timeout = re.search(r"s6-notifyoncheck\b.* -T (\d+)", run)

    assert (service / "notification-fd").read_text().strip() == "3"
    assert notify_timeout is not None
    assert int((service / "timeout-up").read_text().strip()) > int(notify_timeout.group(1))
    assert probe in run


@pytest.mark.parametrize(
    "service",
    sorted(path.parent for path in _CONTAINER.glob("**/rootfs/etc/s6/s6-rc.d/*/notification-fd")),
)
def test_s6_notifier_runs_before_privilege_drop(service: Path) -> None:
    run = (service / "run").read_text()

    if "s6-setuidgid" in run:
        assert run.index("s6-notifyoncheck") < run.index("s6-setuidgid")


@pytest.mark.parametrize("entrypoint", _s6_service_entrypoints())
def test_s6_service_processes_run_as_x(entrypoint: Path) -> None:
    run = entrypoint.read_text()

    assert "s6-setuidgid x" in run
    assert "s6-env HOME=/home/x" in run


@pytest.mark.parametrize("service", ["vllm", "sglang"])
def test_inference_entrypoint_uses_fixed_bridge_listener(tmp_path: Path, service: str) -> None:
    venv = tmp_path / "venv"
    binary = venv / "bin" / ("vllm" if service == "vllm" else "python")
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n")
    binary.chmod(0o755)
    source = (_CONTAINER / f"services/{service}/rootfs/opt/{service}/serve.sh").read_text()
    script = tmp_path / f"{service}-serve.sh"
    script.write_text(source.replace(f"/opt/{service}/venv", str(venv)))
    environment = {key: value for key, value in os.environ.items() if not key.startswith("SERVE_")}
    environment["SERVE_EXTRA_ARGS"] = "--max-model-len 8192"

    result = subprocess.run(
        ["bash", str(script)],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    args = result.stdout.splitlines()
    assert args[args.index("--host") + 1] == "0.0.0.0"
    assert args[args.index("--port") + 1] == "8080"
    if service == "vllm":
        assert args[-2:] == ["--max-model-len", "8192"]
