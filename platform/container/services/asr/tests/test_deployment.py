import ast
import asyncio
import os
import subprocess
from pathlib import Path

from models.catalog import MODELS
from ops.scheduler import Scheduler
from server.config import Config


def test_each_model_has_static_download_serve_chain() -> None:
    root = Path(__file__).resolve().parents[1]
    graph = root / "rootfs/etc/s6/s6-rc.d"
    for spec in MODELS:
        directory = root / "models" / spec.id
        for script in ("run", "download_model.sh"):
            subprocess.run(["bash", "-n", str(directory / script)], check=True)
        assert (directory / "client.py").is_file()
        for source in directory.glob("*.py"):
            ast.parse(source.read_text(), filename=str(source))
        download = graph / f"asr-{spec.id}-download"
        serve = graph / f"asr-{spec.id}"
        assert (serve / f"dependencies.d/asr-{spec.id}-download").is_file()
        assert "s6-setuidgid x" in (serve / "run").read_text()
        assert "download_model.sh" in (download / "up").read_text()
        assert "hf download" in (directory / "download_model.sh").read_text()
        assert not (directory / "download_model.py").exists()


def test_image_does_not_download_weights() -> None:
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert "AS prepared" not in dockerfile
    assert "download_model" not in dockerfile


def test_model_clients_match_fixed_listeners(tmp_path: Path) -> None:
    uv = tmp_path / "uv"
    uv.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n')
    uv.chmod(0o755)
    scheduler = Scheduler(Config())
    try:
        ports = set()
        for instance in scheduler.instances.values():
            result = subprocess.run(
                [str(instance.directory / "run")],
                env={
                    **os.environ,
                    "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
                    "ASR_HOST": "127.0.0.2",
                    "ASR_PORT": "65535",
                },
                cwd=tmp_path,
                check=True,
                text=True,
                capture_output=True,
            )
            args = result.stdout.splitlines()
            host = args[args.index("--host") + 1]
            port = int(args[args.index("--port") + 1])
            assert host == "127.0.0.1"
            assert instance.url == f"http://{host}:{port}"
            assert port not in ports
            ports.add(port)
        assert ports == set(range(8000, 8013))
    finally:
        asyncio.run(scheduler.close())
