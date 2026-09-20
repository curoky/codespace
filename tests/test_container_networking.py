"""Behavior checks for executable container entrypoints."""

# ruff: noqa: S104, S603, S607

import os
import re
import subprocess
from pathlib import Path

import pytest

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
        _CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d/hosts-blackhole/up",
        _CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d/miniserve-http/run",
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


def test_workspace_hosts_blackhole_limits_privilege_to_the_append() -> None:
    helper = _CONTAINER / "workspace/rootfs/opt/codespace/bin/init-hosts-blackhole"

    assert "} | sudo tee -a /etc/hosts >/dev/null" in helper.read_text()


def test_workspace_user_services_load_container_environment_before_dropping_privileges() -> None:
    service_root = _CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d"
    entrypoints = sorted(service_root.glob("*/run")) + sorted(service_root.glob("*/up"))

    for entrypoint in entrypoints:
        lines = entrypoint.read_text().splitlines()
        if "s6-setuidgid x" not in lines:
            continue
        assert "s6-envdir -Lf -- /run/s6/container_environment" in lines, entrypoint
        assert lines.index("s6-envdir -Lf -- /run/s6/container_environment") < lines.index(
            "s6-setuidgid x"
        ), entrypoint


def test_log_server_listener_is_configured_by_each_image() -> None:
    run = (_CONTAINER / "workspace/rootfs/etc/s6/s6-rc.d/miniserve-http/run").read_text()
    workspace = (_CONTAINER / "workspace/Dockerfile").read_text()
    service = (_CONTAINER / "services/s6/Dockerfile").read_text()

    assert "importas -S -D 127.0.0.1 MINISERVE_INTERFACES" in run
    assert "--interfaces ${MINISERVE_INTERFACES}" in run
    assert "exec /opt/bm/store/miniserve/bin/miniserve" in run
    assert "MINISERVE_INTERFACES" not in workspace
    assert "MINISERVE_INTERFACES=0.0.0.0" in service
    assert "chown -R x:x /opt/bm" in service


def test_s6_services_use_store_paths_for_binman_commands() -> None:
    command = re.compile(
        r"(?<![/\w-])(?:atuin|gh|miniserve|nixcache|rclone|sshd|supercronic)(?=\s)"
    )
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
    binary.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
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
