"""Image entrypoints must preserve bridge reachability and loopback isolation."""

# ruff: noqa: S104, S603, S607

import configparser
import mimetypes
import os
import subprocess
from pathlib import Path

import pytest

_CONTAINER = Path(__file__).resolve().parents[1] / "platform/container"
_SERVICES = _CONTAINER / "services"
_WORKSPACE_ROOT = _CONTAINER / "workspace/rootfs"
_WORKSPACE_AGENT = _CONTAINER / "workspace/agent/agent.py"
_WSL_BOOT = Path(__file__).resolve().parents[1] / "platform/wsl/rootfs/opt/codespace/wsl/boot.sh"


@pytest.mark.parametrize("service", ["chatbox", "lobehub", "secret", "sglang", "support", "vllm"])
def test_service_images_use_s6_without_expose_metadata(service: str) -> None:
    dockerfile = (_SERVICES / service / "Dockerfile").read_text()

    assert "service-s6" in dockerfile
    assert "EXPOSE" not in dockerfile


@pytest.mark.parametrize("service", ["vllm", "sglang"])
def test_inference_entrypoint_uses_fixed_bridge_listener(tmp_path: Path, service: str) -> None:
    venv = tmp_path / "venv"
    binary = venv / "bin" / ("vllm" if service == "vllm" else "python")
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
    binary.chmod(0o755)
    source = (_CONTAINER / f"services/{service}/rootfs/opt/{service}/serve.sh").read_text()
    assert "SERVE_VENV" not in source
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


def test_secret_entrypoint_uses_fixed_bridge_listener() -> None:
    script = (_CONTAINER / "services/secret/rootfs/opt/secret/serve.sh").read_text()
    service = _CONTAINER / "services/secret/rootfs/etc/s6/s6-rc.d/serve"
    run = (service / "run").read_text()

    assert '--addr "0.0.0.0:8080"' in script
    assert "SERVE_HOST" not in script
    assert "SERVE_PORT" not in script
    assert "SERVE_ROOT" not in script
    assert "SERVE_USER" not in script
    assert "SERVE_PASS" not in script
    assert "readonly root=/srv" in script
    assert "readonly pass_file=/run/secrets/secret_webdav_password" in script
    assert (service / "notification-fd").read_text().strip() == "3"
    assert (service / "timeout-up").read_text().strip() == "35000"
    assert "s6-notifyoncheck" in run
    assert "--user" in run
    assert "secret_webdav_password" in run
    assert "http://127.0.0.1:8080/" in run


def test_sglang_runtime_copies_binman_before_installing_uv() -> None:
    dockerfile = (_CONTAINER / "services/sglang/Dockerfile").read_text()

    assert dockerfile.index("COPY --from=s6 /opt/bm /opt/bm") < dockerfile.index(
        "RUN /opt/bm/bin/bm install uv"
    )


def test_workspace_secret_mount_only_configures_gateway_url() -> None:
    path = _WORKSPACE_ROOT / "opt/codespace/bin/mount-secret"
    script = path.read_text()

    assert os.access(path, os.X_OK)
    assert "CODESPACE_SECRET_URL" in script
    for name in (
        "CODESPACE_SECRET_MOUNT",
        "CODESPACE_SECRET_USER",
        "CODESPACE_SECRET_PASS",
        "${RCLONE",
    ):
        assert name not in script
    assert "readonly mount_point=/mnt/secret" in script
    assert "RCLONE_CONFIG_SECRET_USER=codespace" in script


@pytest.mark.parametrize(
    ("service", "listen"),
    [
        ("rclone-webdav", "--addr 127.0.0.1:8004"),
        ("copyparty-webdav", "-i 127.0.0.1"),
        ("rclone-http", "--addr 127.0.0.1:8007"),
        ("miniserve-http", "--interfaces 127.0.0.1"),
        ("nixcache", "--host 127.0.0.1"),
    ],
)
def test_workspace_file_services_use_fixed_loopback_listener(service: str, listen: str) -> None:
    script = (_WORKSPACE_ROOT / f"etc/s6/s6-rc.d/{service}/run").read_text()

    assert listen in script
    assert "SERVE_HOST" not in script
    assert "SSHD_BIND" not in script


def test_workspace_rclone_services_share_combined_remote() -> None:
    config = configparser.ConfigParser()
    config.read(_WORKSPACE_ROOT / "etc/rclone.conf")

    assert config["files"]["type"] == "combine"
    assert config["files"]["upstreams"].split() == [
        "workspace=workspace:",
        "logs=logs:",
        "upload=/upload",
    ]
    assert config["logs"]["upstreams"].split() == ["/var/log:ro", "empty::ro"]
    for service, protocol in (("rclone-webdav", "webdav"), ("rclone-http", "http")):
        script = (_WORKSPACE_ROOT / f"etc/s6/s6-rc.d/{service}/run").read_text()
        assert f"rclone serve {protocol} files:" in script
        assert "--config /etc/rclone.conf" in script
        assert (_WORKSPACE_ROOT / f"etc/s6/s6-rc.d/default/contents.d/{service}").exists()
        assert (
            _WORKSPACE_ROOT / f"etc/s6/s6-rc.d/{service}/dependencies.d/workspace-init"
        ).exists()

    http_script = (_WORKSPACE_ROOT / "etc/s6/s6-rc.d/rclone-http/run").read_text()
    assert "--disable-dir-list" not in http_script
    assert '--response-header "Content-Disposition: inline"' in http_script

    mime_types = mimetypes.read_mime_types(_WORKSPACE_ROOT / "etc/mime.types")
    assert mime_types is not None
    for extension in (".log", ".toml", ".yaml", ".py", ".go"):
        assert mime_types[extension].startswith("text/")


def test_workspace_copyparty_exposes_container_logs_read_only() -> None:
    script = (_WORKSPACE_ROOT / "etc/s6/s6-rc.d/copyparty-webdav/run").read_text()

    assert "-v /var/log:logs:r\n" in script


def test_workspace_miniserve_exposes_container_logs_read_only() -> None:
    service = _WORKSPACE_ROOT / "etc/s6/s6-rc.d/miniserve-http"
    script = (service / "run").read_text()

    assert "exec /opt/bm/bin/miniserve" in script
    assert "--port 8008" in script
    assert "--no-symlinks" in script
    assert script.rstrip().endswith("/var/log")
    for setting in (
        "MINISERVE_ENABLE_TAR",
        "MINISERVE_ENABLE_TAR_GZ",
        "MINISERVE_ENABLE_ZIP",
        "MINISERVE_SHOW_SYMLINK_INFO",
        "MINISERVE_SHOW_WGET_FOOTER",
    ):
        assert f"s6-env {setting}=false" in script
    assert all(option not in script for option in ("--upload-files", "--mkdir", "--rm-files"))
    assert (_WORKSPACE_ROOT / "etc/s6/s6-rc.d/default/contents.d/miniserve-http").exists()


def test_workspace_nixcache_runs_as_user_in_default_bundle() -> None:
    service = _WORKSPACE_ROOT / "etc/s6/s6-rc.d/nixcache"
    script = (service / "run").read_text()

    assert (service / "type").read_text().strip() == "longrun"
    assert os.access(service / "run", os.X_OK)
    assert "s6-envdir -Lf -- /run/s6/container_environment" in script
    assert "redirfd -w 1 /var/log/s6.nixcache.log" in script
    assert "fdmove -c 2 1" in script
    assert "s6-setuidgid x\ns6-env HOME=/home/x\n" in script
    assert "exec /opt/bm/bin/nixcache serve\n  --host 127.0.0.1\n  --port 8009\n" in script
    assert (_WORKSPACE_ROOT / "etc/s6/s6-rc.d/default/contents.d/nixcache").is_file()


def test_workspace_sshd_uses_fixed_listener() -> None:
    service = _WORKSPACE_ROOT / "etc/s6/s6-rc.d/sshd"
    script = (service / "run").read_text()
    config = (_WORKSPACE_ROOT / "etc/ssh/sshd_config").read_text()

    assert "SSHD_PORT" not in script
    assert "SSHD_BIND" not in script
    assert "redirfd -w 1 /var/log/s6.sshd.log" in script
    assert "s6.sshd.stdout.log" not in script
    assert "sshd -D -e" in script
    assert "\n  -E " not in script
    assert "\nPort 22\n" in config
    assert "\nListenAddress 0.0.0.0\n" in config
    assert "s6-notifyoncheck" in script
    assert "s6-tcpclient -H -t 1 127.0.0.1 22 /bin/true" in script
    assert (service / "notification-fd").read_text().strip() == "3"


def test_workspace_ollama_uses_fixed_loopback_listener() -> None:
    script = (_WORKSPACE_ROOT / "etc/s6/s6-rc.d/ollama/run").read_text()

    assert "export OLLAMA_HOST 127.0.0.1:8006" in script
    assert "importas" not in script


def test_workspace_agent_requires_managed_bootstrap_environment() -> None:
    source = _WORKSPACE_AGENT.read_text()

    for name in ("CODESPACE_SOURCE_TYPE", "CODESPACE_CHECKOUT_PATH", "CODESPACE_OPEN_PATH"):
        assert f'os.environ["{name}"]' in source
    assert 'os.environ.get("CODESPACE_SOURCE_TYPE")' not in source
    assert "signal.pause" not in source


def test_wsl_declares_inherited_workspace_runtime_input() -> None:
    script = _WSL_BOOT.read_text()

    assert "container_environment/CODESPACE_ENCRYPTED" in script
    assert "container_environment/CODESPACE_ENCRYPTED_PATH" in script
    assert "SSHD_PORT" not in script
    assert "SSHD_BIND" not in script

    graph = _WORKSPACE_ROOT / "etc/s6/s6-rc.d"
    dependencies = {
        "home-init": set(),
        "sshd": {"home-init", "workspace-init"},
        "workspace-agent": {"sshd"},
    }
    for service, expected in dependencies.items():
        assert {path.name for path in (graph / service / "dependencies.d").glob("*")} == expected
    bundle = _WSL_BOOT.parents[3] / "etc/s6/s6-rc.d/wsl/contents.d"
    assert (bundle / "sshd").exists()
    assert not (bundle / "workspace-agent").exists()
