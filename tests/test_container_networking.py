"""Behavior checks for executable container entrypoints."""

# ruff: noqa: S104, S603, S607

import json
import os
import re
import subprocess
import sys
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
        _CONTAINER / "workspace/rootfs/etc/s6/archive/atuin-server/run",
        _CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d/miniserve-logs/run",
        _CONTAINER / "workspace/rootfs/etc/s6/archive/ollama/run",
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
    assert (workspace / "rootfs/etc/s6/archive/atuin-server/run").exists()
    assert (services / "atuin-login/up").exists()
    assert (services / "default/contents.d/atuin-login").exists()
    assert not (services / "default/contents.d/atuin-server").exists()
    assert (services / "atuin-daemon/dependencies.d/atuin-login").exists()
    assert not (services / "atuin-login/dependencies.d/atuin-server").exists()
    assert login.count("/home/x/.local/bin/csecret get atuin_credentials") == 3
    assert "/run/secrets/atuin_credentials" not in login
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

    public_token = "github_token_public_read"
    actions_token = "github_token_all_action_rw"
    assert f"pipeline {{ /home/x/.local/bin/csecret get {public_token} }}" in login
    assert "/run/secrets/" not in login
    assert actions_token not in login
    assert f'token="$(csecret get {actions_token})"' in github_skill
    assert 'GH_TOKEN="$token" gh run view --log-failed' in github_skill


def test_workspace_agents_share_codex_skills() -> None:
    home = _CONTAINER / "workspace/rootfs/home/x"

    for skill in ("debug-github", "manage-services"):
        target = f"../../.codex/skills/{skill}"
        assert (home / ".trae/skills" / skill).readlink() == Path(target)
        assert (home / ".trae-cn/skills" / skill).readlink() == Path(target)


def test_app_profile_prioritizes_managed_tools_and_preserves_inherited_environment(
    tmp_path: Path,
) -> None:
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
    assert entries[0] == str(tmp_path / ".local/bin")
    assert entries.index(str(tmp_path / ".local/opt/uv/bin")) < entries.index("/usr/bin")
    assert entries.index("/nix/var/nix/profiles/default/bin") < entries.index("/usr/bin")
    assert len(entries) == len(set(entries))
    assert {"/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/sbin"}.isdisjoint(entries)
    assert {
        "/usr/local/profile/go/bin",
        "/usr/local/profile/clang-tools/bin",
        "/usr/local/profile/protobuf/bin",
        str(tmp_path / "go/bin"),
        str(tmp_path / ".local/opt/go/go1.27/bin"),
        str(tmp_path / ".cargo/bin"),
        str(tmp_path / ".local/opt/rust/cargo/bin"),
        str(tmp_path / ".local/opt/llvm/llvm23/bin"),
        str(tmp_path / ".local/share/pnpm/bin"),
        str(tmp_path / ".local/opt/uv/bin"),
        str(tmp_path / ".local/opt/conda/condabin"),
        str(tmp_path / ".local/opt/java"),
        str(tmp_path / ".local/opt/java/openjdk27/bin"),
        str(tmp_path / ".local/opt/node"),
        str(tmp_path / ".local/opt/node/tools/bin"),
        str(tmp_path / ".local/opt/node/nodejs26/bin"),
    }.issubset(entries)
    assert environment["JAVA_HOME"] == str(tmp_path / ".local/opt/java/openjdk27")
    assert environment["UV_TOOL_DIR"] == str(tmp_path / ".local/opt/uv/tools")
    assert environment["UV_TOOL_BIN_DIR"] == str(tmp_path / ".local/opt/uv/bin")
    assert environment["UV_PYTHON_INSTALL_DIR"] == str(tmp_path / ".local/opt/uv/python")
    assert environment["UV_PYTHON_BIN_DIR"] == str(tmp_path / ".local/opt/uv/bin")
    assert environment["CARGO_HOME"] == str(tmp_path / ".cargo")
    assert environment["RUSTUP_HOME"] == str(tmp_path / ".local/opt/rust/rustup")
    assert environment["LD_LIBRARY_PATH"] == "/usr/local/cuda/lib64"


def test_app_profile_reload_preserves_project_toolchain_override(tmp_path: Path) -> None:
    profile = _CONTAINER / "workspace/rootfs/etc/profile.d/app.sh"
    result = subprocess.run(
        [
            "/bin/bash",
            "-eu",
            "-c",
            '. "$1"; PATH="/project/venv/bin:$PATH"; before="$PATH"; '
            '. "$1"; test "$PATH" = "$before"',
            "profile-test",
            str(profile),
        ],
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()


def test_gcc_defaults_use_declared_native_package_managers() -> None:
    workspace = _CONTAINER / "workspace"
    macos = _CONTAINER.parent / "macos"
    dockerfile = (workspace / "Dockerfile").read_text()
    assert "nix-env -iA nixpkgs.gcc16 -p /nix/var/nix/profiles/default" in dockerfile
    assert "nixpkgs.gcc15" not in dockerfile
    assert 'brew "gcc"' in (macos / "Brewfile").read_text()
    installer = (macos / "maintenance/homebrew.sh").read_text()
    for name in ("gcc", "g++"):
        assert f"test -x /opt/homebrew/opt/gcc/bin/{name}-16" in installer
        assert f'ln -sfn /opt/homebrew/opt/gcc/bin/{name}-16 "$HOME/.local/bin/{name}"' in installer


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
    assert "/usr/local/bin/s6-setuidgid x /usr/local/bin/s6-env HOME=/home/x" in password_init
    assert "/home/x/.local/bin/csecret get codespace_root_password" in password_init
    assert "/run/secrets/codespace_root_password" not in password_init
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
        '"$HOME/.local/bin"' in (_CONTAINER / "workspace/rootfs/etc/profile.d/app.sh").read_text()
    )
    assert "- podman5-rootless" in manifest
    assert "bm download" not in dockerfile


def test_workspace_bundles_runtimes_and_keeps_optional_java_tools_in_resource() -> None:
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

    assert '"$HOME/.local/opt/java/tools/bin"' in profile
    assert "/opt/resource/home/x/.local/opt/java/tools/bin" in profile
    assert '"$HOME/.local/opt/node/tools/bin"' in profile
    assert "/opt/resource/home/x/.local/opt/node" not in profile
    for family in ("java", "node", "rust", "go"):
        assert (
            f"COPY --link --chown=5230:5230 --from=stage_{family} "
            f"/home/x/.local/opt/{family} /home/x/.local/opt/{family}" in workspace_dockerfile
        )
        assert not (rootfs_opt / family).exists()
    assert "ENV HOME=/home/x" in resource_dockerfile
    assert "RUN node-tool install" in workspace_dockerfile
    assert (
        "COPY --from=stage_java /home/x/.local/opt/java/tools "
        "/opt/resource/home/x/.local/opt/java/tools" in resource_dockerfile
    )
    for family in ("go", "node", "rust"):
        assert f"COPY --from=stage_{family}" not in resource_dockerfile
    assert "FROM payload AS test" in resource_dockerfile
    assert "FROM test AS resource" in resource_dockerfile
    assert settings["prettier.prettierPath"].startswith("/home/x/.local/opt/node/tools/")
    assert settings["typescript.npm"] == "/home/x/.local/opt/node/nodejs26/bin/npm"
    assert settings["xml.server.binary.path"] == "/home/x/.local/opt/java/tools/bin/lemminx"
    assert settings["java.jdt.ls.java.home"] == "/home/x/.local/opt/java/openjdk27"
    assert actual_links == expected_links


def test_workspace_keeps_required_python_and_bundles_python_tools() -> None:
    workspace = _CONTAINER / "workspace"
    dockerfile = (workspace / "Dockerfile").read_text()
    resource_dockerfile = (workspace / "resource.Dockerfile").read_text()
    profile = (workspace / "rootfs/etc/profile.d/app.sh").read_text()
    assert "uv python install --default 3.15.2" in dockerfile
    runtime_stage = dockerfile.split("FROM docker.io/$BASE_IMAGE AS workspace\n", 1)[1]
    assert not any(line.startswith("ENV ") for line in runtime_stage.splitlines())
    assert (
        "COPY --link --chown=5230:5230 --from=stage_python "
        "/home/x/.local/opt/uv /home/x/.local/opt/uv" in runtime_stage
    )
    assert '"$UV_PYTHON_BIN_DIR"' in profile
    assert "UV_PYTHON_BIN_DIR=/home/x/.local/opt/uv/bin" in dockerfile
    assert "uv sync --project /opt/codespace-agent" not in runtime_stage
    python_tools = {
        "copyparty",
        "licenseheaders",
        "netron",
        "mitmproxy",
        "git-filter-repo",
    }
    for tool in (*python_tools, "dool"):
        assert f'uv tool install {tool} --python "$UV_PYTHON_BIN_DIR/python3.15"' in dockerfile
    settings = json.loads(
        (workspace / "rootfs/home/x/.vscode-server/data/Machine/settings.json").read_text()
    )
    assert settings["python.defaultInterpreterPath"] == "/home/x/.local/opt/uv/bin/python3.15"

    python_install = re.search(r"uv python install --no-bin ([^\n]+)", resource_dockerfile)
    assert python_install is not None
    python_versions = python_install.group(1).removesuffix("\\").split()
    assert "FROM ghcr.io/astral-sh/uv:" not in resource_dockerfile
    assert (
        "COPY --from=stage_build_tools /usr/local/store/uv/bin/uv /usr/local/bin/uv"
        in resource_dockerfile
    )
    assert "uv tool install dool" in dockerfile
    for tool in (*python_tools, "dool"):
        assert f"uv tool install {tool}" not in resource_dockerfile
    resource_tools = {"tensorboard": "3.12.16"}
    for tool, python in resource_tools.items():
        minor = ".".join(python.split(".")[:2])
        assert f"uv tool install {tool}" in resource_dockerfile
        assert (
            f"--python /opt/resource/home/x/.local/opt/uv/python/cpython-{python}-linux-x86_64-gnu/"
            f"bin/python{minor}" in resource_dockerfile
        )
        assert f"uv tool install {tool}" not in dockerfile
    assert "/opt/resource/home/x/.local/opt/uv/bin" in profile
    python_root = workspace / "rootfs/home/x/.local/opt/uv/python"
    installations = {path.name: path for path in python_root.iterdir() if not path.is_symlink()}
    aliases = {path.name: path.readlink() for path in python_root.iterdir() if path.is_symlink()}
    assert set(installations) == {
        f"cpython-{version}-linux-x86_64-gnu" for version in python_versions if version != "3.15.2"
    }
    assert aliases == {
        f"cpython-{'.'.join(version.split('.')[:2])}-linux-x86_64-gnu": Path(
            f"cpython-{version}-linux-x86_64-gnu"
        )
        for version in python_versions
        if version != "3.15.2"
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
                == Path("/opt/resource/home/x/.local/opt/uv/python")
                / installation.name
                / child.name
            )


def test_conda_uses_the_current_home_for_its_installation_and_environment_helper(
    tmp_path: Path,
) -> None:
    home = tmp_path / "client home"
    root = home / ".local/opt/conda"
    conda = root / "bin/conda"
    conda.parent.mkdir(parents=True)
    record = tmp_path / "calls"
    conda.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, sys\n"
        "root = pathlib.Path(os.environ['CONDA_ROOT'])\n"
        "with pathlib.Path(os.environ['TEST_RECORD']).open('a') as output:\n"
        "    output.write(json.dumps([str(root), os.environ['PATH'], sys.argv[1:]]) + '\\n')\n"
        "if sys.argv[1] == 'create':\n"
        "    (root / 'envs/smoke/compiler_compat').mkdir(parents=True)\n"
        "if sys.argv[1:3] == ['env', 'export']:\n"
        "    print('name: smoke')\n"
    )
    conda.chmod(0o755)
    environment_file = tmp_path / "environment.yaml"
    environment_file.write_text("name: smoke\ndependencies:\n  - python=3.14\n")
    # GNU getopt belongs to the Linux image, not the native macOS test environment.
    getopt = tmp_path / "getopt"
    getopt.write_text(
        f"#!{sys.executable}\n"
        "import shlex, sys\n"
        "arguments = sys.argv[sys.argv.index('--') + 1:]\n"
        "print(shlex.join([*arguments, '--']))\n"
    )
    getopt.chmod(0o755)
    subprocess.run(
        [
            "bash",
            str(_CONTAINER / "workspace/scripts/install-conda-environment.sh"),
            "-e",
            str(environment_file),
        ],
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "TEST_RECORD": str(record),
        },
        check=True,
        capture_output=True,
        text=True,
    )
    calls = [json.loads(line) for line in record.read_text().splitlines()]
    assert [call[2] for call in calls] == [
        ["create", "-n", "smoke", "python=3.14", "-y", "--no-default-packages"],
        ["env", "update", "-f", str(environment_file)],
        ["env", "export", "-n", "smoke"],
    ]
    assert all(call[0] == str(root) and call[1].startswith(f"{root}/bin:") for call in calls)
    assert environment_file.with_name("environment-lock.yaml").read_text() == "name: smoke\n"
    workspace = _CONTAINER / "workspace"
    dockerfile = (workspace / "Dockerfile").read_text()
    assert "bash /tmp/miniconda.sh -b -u -p /home/x/.local/opt/conda" in dockerfile
    assert (
        "COPY --link --chown=5230:5230 --from=stage_conda "
        "/home/x/.local/opt/conda /home/x/.local/opt/conda" in dockerfile
    )
    assert (
        'source "$HOME/.local/opt/conda/etc/profile.d/conda.sh"'
        in (workspace / "rootfs/home/x/.zshrc").read_text()
    )


@pytest.mark.skipif(
    sys.platform != "linux" or os.uname().machine != "x86_64",
    reason="Workspace Python installations target Linux x86_64",
)
def test_uv_discovers_linked_python_and_creates_a_venv(tmp_path: Path) -> None:
    version = ".".join(str(part) for part in sys.version_info[:3])
    minor = ".".join(str(part) for part in sys.version_info[:2])
    environment = dict(os.environ)
    environment.pop("VIRTUAL_ENV", None)
    runtime = subprocess.run(
        [
            "uv",
            "python",
            "find",
            "--no-project",
            "--no-config",
            "--managed-python",
            "--offline",
            "--no-python-downloads",
            version,
        ],
        env=environment,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    runtime_root = Path(runtime.stdout.strip()).parent.parent
    python_root = tmp_path / "python"
    installation = python_root / f"cpython-{version}-linux-x86_64-gnu"
    installation.mkdir(parents=True)
    alias = python_root / f"cpython-{minor}-linux-x86_64-gnu"
    alias.symlink_to(installation.name)
    declarations = _CONTAINER / "workspace/rootfs/home/x/.local/opt/uv/python"
    for child in next(path for path in declarations.iterdir() if not path.is_symlink()).iterdir():
        (installation / child.name).symlink_to(runtime_root / child.name)
    environment["UV_PYTHON_INSTALL_DIR"] = str(python_root)
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


def test_workspace_bundles_compiled_executables() -> None:
    workspace = _CONTAINER / "workspace"
    dockerfile = (workspace / "Dockerfile").read_text()
    resource_dockerfile = (workspace / "resource.Dockerfile").read_text()
    profile = (workspace / "rootfs/etc/profile.d/app.sh").read_text()

    assert "FROM docker.io/golang:1.27.4 AS stage_workspace_tools" in dockerfile
    assert "ENV CGO_ENABLED=0" in dockerfile
    assert "ARG TARGETOS" not in dockerfile
    assert "ARG TARGETARCH" not in dockerfile
    assert "/out/workspace-agent /opt/codespace-agent/workspace-agent" in dockerfile
    assert "/out/node-tool /home/x/.local/opt/node/node-tool" in dockerfile
    assert "/out/java-tool /home/x/.local/opt/java/java-tool" in dockerfile
    assert (
        "COPY --from=stage_java_tool /out/java-tool /usr/local/bin/java-tool" in resource_dockerfile
    )
    assert "node-tool" not in resource_dockerfile
    for name in ("node-tool", "java-tool"):
        tool = workspace / "tools" / name
        assert (tool / "main.go").is_file()
        assert (tool / "launcher.bash.tmpl").is_file()
        assert not (tool / "pyproject.toml").exists()
        assert not (tool / "uv.lock").exists()
        assert not (tool / f"{name}.py").exists()
    assert "--pnpm" not in dockerfile
    assert "--root /home/x/.local/opt/node/tools" not in dockerfile
    assert "--root /home/x/.local/opt/java/tools" not in resource_dockerfile
    assert '"$HOME/.local/opt/java"' in profile
    assert '"$HOME/.local/opt/node"' in profile


@pytest.mark.parametrize("name", ["node-tool", "java-tool"])
def test_compiled_tool_needs_no_python_environment(
    tmp_path: Path, workspace_binaries: dict[str, Path], name: str
) -> None:
    environment = {
        "HOME": str(tmp_path),
        "PATH": "/missing",
        "VIRTUAL_ENV": str(tmp_path / "caller"),
        "UV_PROJECT_ENVIRONMENT": str(tmp_path / "project"),
    }
    result = subprocess.run(
        [str(workspace_binaries[name]), "--help"],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert name in result.stdout
    assert not (tmp_path / "project").exists()
    result = subprocess.run(
        [str(workspace_binaries[name]), "init"],
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert 'unknown command "init"' in result.stderr


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
    assert "test ! -e /opt/resource/home/x/.local/opt/uv/bin/uv" in dockerfile
    assert "test ! -e /opt/resource/usr/local/store/uv" in dockerfile
    assert "test ! -e /opt/resource/usr/local/store/pnpm" in dockerfile
    assert "test ! -e /opt/resource/home/x/.local/opt/node" in dockerfile
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
        (_CONTAINER.parent / "macos/binman.yaml", None),
    ],
)
def test_binman_manifests_use_install_plan_schema(manifest_path: Path, prefix: str | None) -> None:
    manifest = yaml.safe_load(manifest_path.read_text())

    assert set(manifest) == ({"prefix", "installs"} if prefix else {"installs"})
    assert manifest.get("prefix") == prefix
    assert manifest["installs"]
    for install in manifest["installs"]:
        assert set(install) <= {"packages", "link-to"}
        assert install["packages"]


def test_macos_toolchains_match_workspace_versions() -> None:
    dockerfile = (_CONTAINER / "workspace/Dockerfile").read_text()
    maintenance = _CONTAINER.parent / "macos/maintenance"
    node_runtime = (maintenance / "node-runtime.sh").read_text()
    node_tools = (maintenance / "node-tools.sh").read_text()
    go = (maintenance / "go.sh").read_text()
    java = (maintenance / "java-runtime.sh").read_text()

    node_versions = set(re.findall(r"node-v(\d+\.\d+\.\d+)-linux-x64", dockerfile))
    assert len(node_versions) == 2
    for version in node_versions:
        assert version in node_runtime

    go_version = re.search(r"go(\d+\.\d+\.\d+)\.linux-amd64", dockerfile)
    assert go_version is not None
    assert f'version="{go_version.group(1)}"' in go

    java_version = re.search(r"releases/download/jdk-(\d+(?:\.\d+)*)%2B(\d+)/", dockerfile)
    assert java_version is not None
    version, build = java_version.groups()
    major = version.split(".")[0]
    assert f'version="{version}+{build}"' in java
    assert (
        f"jdk-{version}%2B{build}/OpenJDK{major}U-jdk_aarch64_mac_hotspot_{version}_{build}" in java
    )
    assert f'destination="$HOME/.local/opt/java/openjdk{major}"' in java

    node_packages = set(re.findall(r"node-tool install ([\w-]+@\d+\.\d+\.\d+)", dockerfile))
    assert node_packages == {"defuddle@0.19.4", "markdownlint-cli2@0.23.3", "prettier@3.9.9"}
    assert set(re.findall(r"[\w-]+@\d+\.\d+\.\d+", node_tools)) == node_packages
    assert '"$oras" pull ghcr.io/curoky/codespace:node-tool-darwin-arm64' in node_tools
    assert "go1." not in node_tools
    assert 'node_root="$HOME/.local/opt/node"' in node_runtime
    assert 'node_root="$HOME/.local/opt/node"' in node_tools
    for package in node_packages:
        assert f"node-tool install {package}" in node_tools
    assert "--node" not in node_tools
    assert "--pnpm" not in node_tools
    assert "--root" not in node_tools

    macos_manifest = yaml.safe_load((_CONTAINER.parent / "macos/binman.yaml").read_text())
    macos_packages = {
        package for install in macos_manifest["installs"] for package in install["packages"]
    }
    assert {"pnpm", "uv", "oras"} <= macos_packages


def test_macos_installers_use_published_arm64_artifacts() -> None:
    workspace = _CONTAINER / "workspace"
    macos = _CONTAINER.parent / "macos"
    workflow_path = _CONTAINER.parent.parent / ".github/workflows/publish-workspace-tools.yaml"
    workflow = yaml.safe_load(workflow_path.read_text())
    publish = workflow["jobs"]["publish"]
    assert publish["runs-on"] == "macos-15"
    assert publish["strategy"]["matrix"]["tool"] == ["node-tool", "java-tool"]
    steps = publish["steps"]
    build = next(step for step in steps if step.get("name") == "Build macOS arm64 binary")
    assert build["env"]["GOOS"] == "darwin"
    assert build["env"]["GOARCH"] == "arm64"
    assert build["env"]["CGO_ENABLED"] == "0"
    assert any(step.get("uses") == "oras-project/setup-oras@v2.0.4" for step in steps)
    assert not any(step.get("uses", "").startswith("docker/") for step in steps)
    publish_script = next(
        step["run"] for step in steps if step.get("name") == "Publish OCI artifact"
    )
    assert "--artifact-platform darwin/arm64" in publish_script
    assert 'oras tag "$reference" "$TOOL-darwin-arm64"' in publish_script
    assert "FROM scratch AS node-tool" not in (workspace / "Dockerfile").read_text()
    assert not (workspace / "tools/Dockerfile").exists()
    for name in ("node", "java"):
        script = (macos / f"maintenance/{name}-tools.sh").read_text()
        assert f'"$oras" pull ghcr.io/curoky/codespace:{name}-tool-darwin-arm64' in script
        assert f'tar -xzf "$work_dir/{name}-tool.tar.gz"' in script
        assert f'install -m 0755 "$work_dir/{name}-tool"' in script
        assert "workspace_source" not in script
        assert "go1." not in script


def test_macos_source_validation_waits_for_successful_publish() -> None:
    workflows = _CONTAINER.parent.parent / ".github/workflows"
    validation = yaml.safe_load((workflows / "check-macos.yaml").read_text())
    publish = yaml.safe_load((workflows / "publish-workspace-tools.yaml").read_text())
    # PyYAML follows YAML 1.1, where an unquoted "on" key is a boolean.
    trigger = validation[True]["workflow_run"]
    assert trigger == {
        "workflows": [publish["name"]],
        "types": ["completed"],
        "branches": ["master"],
    }
    assert validation["jobs"]["check"]["if"] == (
        "github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'"
    )
    assert "push" not in validation[True]
    assert {
        ".github/workflows/check-macos.yaml",
        ".agents/skills/manage-macos-environment/**",
        "platform/macos/**",
        "platform/container/workspace/rootfs/home/x/**",
        "platform/container/workspace/Dockerfile",
    } <= set(publish[True]["push"]["paths"])


def test_checks_require_managed_python() -> None:
    workflow_path = _CONTAINER.parent.parent / ".github/workflows/checks.yaml"
    workflow = yaml.safe_load(workflow_path.read_text())
    assert workflow["jobs"]["check"]["env"]["UV_MANAGED_PYTHON"] == "true"


def test_macos_java_configuration_uses_only_the_managed_jdk() -> None:
    macos = _CONTAINER.parent / "macos"
    settings = (
        macos / "rootfs/Users/x/Library/Application Support/Code/User/settings.json"
    ).read_text()
    runtimes = re.search(r'"java.configuration.runtimes": (\[.*?\])', settings, re.DOTALL)
    assert runtimes is not None
    assert yaml.safe_load(runtimes.group(1)) == [
        {"default": True, "name": "JavaSE-27", "path": "/Users/x/.local/opt/java/openjdk27"}
    ]
    assert '"java.jdt.ls.java.home": "/Users/x/.local/opt/java/openjdk27"' in settings
    assert "openjdk" not in (macos / "Brewfile").read_text()
    assert "/opt/homebrew/opt/openjdk" not in settings


def test_macos_node_configuration_uses_the_managed_runtime_and_tools() -> None:
    macos = _CONTAINER.parent / "macos"
    settings = (
        macos / "rootfs/Users/x/Library/Application Support/Code/User/settings.json"
    ).read_text()
    assert (
        '"prettier.prettierPath": '
        '"/Users/x/.local/opt/node/tools/envs/prettier/node_modules/prettier"' in settings
    )
    assert '"typescript.npm": "/Users/x/.local/opt/node/nodejs26/bin/npm"' in settings


def test_macos_python_configuration_uses_uv_managed_paths() -> None:
    macos = _CONTAINER.parent / "macos"
    settings = (
        macos / "rootfs/Users/x/Library/Application Support/Code/User/settings.json"
    ).read_text()
    assert '"python.defaultInterpreterPath": "/Users/x/.local/opt/uv/bin/python3.15"' in settings
    uv_script = (macos / "maintenance/uv.sh").read_text()
    assert 'uv_root="$HOME/.local/opt/uv"' in uv_script
    assert '"$HOME/.local/bin/uv" python install --default 3.15.2' in uv_script
    for operation in ("java-tools.sh", "node-tools.sh"):
        script = (macos / "maintenance" / operation).read_text()
        assert "UV_PYTHON_INSTALL_DIR" not in script
        assert "python3.15" not in script


def test_python_cli_ownership_is_aligned_without_package_manager_duplicates() -> None:
    workspace = _CONTAINER / "workspace"
    macos = _CONTAINER.parent / "macos"
    portable_tools = {"copyparty", "licenseheaders", "netron", "mitmproxy", "git-filter-repo"}
    installer = (macos / "maintenance/python-tools.sh").read_text()
    for tool in portable_tools:
        assert (
            f'"$HOME/.local/bin/uv" tool install {tool} --python "$UV_PYTHON_BIN_DIR/python3.15"'
            in installer
        )
    assert installer.count(" tool install ") == len(portable_tools)
    assert 'uv_root="$HOME/.local/opt/uv"' in installer
    for variable, directory in (
        ("UV_TOOL_DIR", "tools"),
        ("UV_TOOL_BIN_DIR", "bin"),
        ("UV_PYTHON_INSTALL_DIR", "python"),
        ("UV_PYTHON_BIN_DIR", "bin"),
    ):
        assert f'export {variable}="$uv_root/{directory}"' in installer
    for manifest_path in (workspace / "config/binman.yaml", macos / "binman.yaml"):
        manifest = yaml.safe_load(manifest_path.read_text())
        packages = {package for install in manifest["installs"] for package in install["packages"]}
        assert not (portable_tools | {"dool", "tensorboard"}) & packages
    brewfile = (macos / "Brewfile").read_text()
    assert not any(f'brew "{package}"' in brewfile for package in portable_tools)


def test_go_installations_and_editor_tools_use_the_home_local_sdk() -> None:
    workspace = _CONTAINER / "workspace"
    macos = _CONTAINER.parent / "macos"
    settings_paths = (
        (workspace / "rootfs/home/x/.vscode-server/data/Machine/settings.json", "/home/x"),
        (macos / "rootfs/Users/x/Library/Application Support/Code/User/settings.json", "/Users/x"),
    )
    for settings_path, home in settings_paths:
        alternate_tools = re.search(r'"go.alternateTools":\s*({[^}]+})', settings_path.read_text())
        assert alternate_tools is not None
        tools = json.loads(alternate_tools.group(1))
        for executable in ("go", "gofmt"):
            assert tools[executable] == f"{home}/.local/opt/go/go1.27/bin/{executable}"
        assert "go-outline" not in tools
        profile = "/usr/local/profile/go" if home == "/home/x" else f"{home}/.local/profile/go"
        assert tools["gopls"] == f"{profile}/bin/gopls"
        for name, path in tools.items():
            if name not in {"go", "gofmt"}:
                assert path.startswith(f"{profile}/bin/")
    assert (
        'destination="$HOME/.local/opt/go/go${version}"'
        in (macos / "maintenance/go.sh").read_text()
    )
    assert '"$HOME/.local/opt/go/go1.27/bin"' in (macos / "rootfs/Users/x/.zshrc").read_text()
    assert (
        "test ! -e /opt/resource/home/x/.local/opt/go"
        in (workspace / "resource.Dockerfile").read_text()
    )


def test_rust_toolchain_installations_are_separate_from_user_cargo_data() -> None:
    workspace = _CONTAINER / "workspace"
    macos = _CONTAINER.parent / "macos"
    dockerfile = (workspace / "Dockerfile").read_text()
    assert (
        "ENV CARGO_HOME=/home/x/.local/opt/rust/cargo "
        "RUSTUP_HOME=/home/x/.local/opt/rust/rustup" in dockerfile
    )
    assert "ENV PATH=/home/x/.local/opt/rust/cargo/bin:${PATH}" in dockerfile
    for source in (dockerfile, (macos / "maintenance/rust.sh").read_text()):
        assert "--profile minimal" in source
        assert "component add clippy rustfmt rust-src rust-analyzer llvm-tools" in source
        assert "--profile default" not in source
        assert "rust-docs" not in source
    assert (
        "test ! -e /opt/resource/home/x/.local/opt/rust"
        in (workspace / "resource.Dockerfile").read_text()
    )
    shell = (macos / "rootfs/Users/x/.zshrc").read_text()
    assert 'export CARGO_HOME="$HOME/.cargo"' in shell
    assert 'export RUSTUP_HOME="$HOME/.local/opt/rust/rustup"' in shell
    assert '"$HOME/.local/opt/rust/cargo/bin"' in shell
    for platform, host in (
        (workspace, "x86_64-unknown-linux-gnu"),
        (macos, "aarch64-apple-darwin"),
    ):
        home_source = "rootfs/home/x" if platform == workspace else "rootfs/Users/x"
        assert (
            f"toolchains/1.100.0-{host}/share/zsh/site-functions"
            in (platform / home_source / ".zshrc").read_text()
        )


def test_macos_go_ci_reads_editor_settings_before_leaving_the_repository() -> None:
    workflow = yaml.safe_load(
        (_CONTAINER.parents[1] / ".github/workflows/check-macos.yaml").read_text()
    )
    script = next(
        step["run"]
        for step in workflow["jobs"]["check"]["steps"]
        if step.get("name") == "Verify native Go SDK and user binary separation"
    )
    assert script.index("settings = Path(") < script.index('cd "$work_dir"')


@pytest.mark.parametrize("change", [None, "missing", "extra"])
def test_macos_rust_ci_checks_native_installed_component_output(
    tmp_path: Path, change: str | None
) -> None:
    workflow = yaml.safe_load(
        (_CONTAINER.parents[1] / ".github/workflows/check-macos.yaml").read_text()
    )
    script = next(
        step["run"]
        for step in workflow["jobs"]["check"]["steps"]
        if step.get("name") == "Verify native Rust SDK and user Cargo separation"
    )
    start = script.index('components="$(rustup component list --installed)"')
    check = script[start : script.index("work_dir=", start)]
    components = [
        "cargo",
        "clippy",
        "llvm-tools",
        "rust-analyzer",
        "rust-src",
        "rust-std",
        "rustc",
        "rustfmt",
    ]
    if change == "missing":
        components.remove("rust-src")
    elif change == "extra":
        components.append("rust-docs")
    names = [name if name == "rust-src" else f"{name}-aarch64-apple-darwin" for name in components]
    rustup = tmp_path / "rustup"
    rustup.write_text("#!/usr/bin/env bash\nprintf '%s\\n' " + " ".join(names) + "\n")
    rustup.chmod(0o755)
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", check],
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        check=False,
    )
    assert (result.returncode == 0) == (change is None)


def test_llvm_sdk_and_formatter_paths_follow_each_platform_contract() -> None:
    workspace = _CONTAINER / "workspace"
    macos = _CONTAINER.parent / "macos"
    link = workspace / "rootfs/home/x/.local/opt/llvm"
    assert link.is_symlink()
    assert link.readlink() == Path("/opt/resource/home/x/.local/opt/llvm")
    assert not (workspace / "rootfs/opt/llvm").exists()
    resource = (workspace / "resource.Dockerfile").read_text()
    assert (
        "COPY --from=stage_llvm /home/x/.local/opt/llvm "
        "/opt/resource/home/x/.local/opt/llvm" in resource
    )
    assert "-C /home/x/.local/opt/llvm/llvm23.1.6" in resource
    assert 'version="23.1.2"' in (macos / "maintenance/llvm.sh").read_text()
    brewfile = (macos / "Brewfile").read_text()
    assert 'brew "llvm"' not in brewfile
    assert 'brew "clang-format"' not in brewfile
    workspace_settings = (
        workspace / "rootfs/home/x/.vscode-server/data/Machine/settings.json"
    ).read_text()
    macos_settings = (
        macos / "rootfs/Users/x/Library/Application Support/Code/User/settings.json"
    ).read_text()
    for field in ("C_Cpp.clang_format_path", "clang-format.executable"):
        assert f'"{field}": "/home/x/.local/opt/llvm/llvm23/bin/clang-format"' in workspace_settings
        assert f'"{field}"' not in macos_settings


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
    ownership = dockerfile.index("chown -hR 5230:5230 /home/x")
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
        ("workspace/rootfs/etc/s6/archive/atuin-server", "127.0.0.1:8002/"),
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
