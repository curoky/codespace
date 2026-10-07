import ast
import asyncio
import os
import subprocess
from pathlib import Path

from models.catalog import MODELS
from ops.scheduler import Scheduler
from server.config import Config

BUNDLED_MODELS = {
    "firered-punc",
    "firered-vad",
    "nemotron-diarization",
    "paraformer",
    "pyannote-community-1",
    "qwen3-aligner",
    "sensevoice",
}


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
        assert "s6-setuidgid x" in (serve / "run").read_text()
        dependency = serve / f"dependencies.d/asr-{spec.id}-download"
        if spec.id in BUNDLED_MODELS:
            assert not download.exists()
            assert not dependency.exists()
        else:
            assert dependency.is_file()
            assert "download_model.sh" in (download / "up").read_text()
        download_script = (directory / "download_model.sh").read_text()
        assert "hf download" in download_script
        assert "--include" in download_script
        assert "--exclude" not in download_script
        assert not (directory / "download_model.py").exists()
        for script in (download_script, (directory / "run").read_text()):
            assert "--frozen" in script
            assert "--no-sync" in script
            assert "--locked" not in script


def test_image_installs_model_environments_in_one_layer() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = root / "install-model-environments.sh"
    subprocess.run(["bash", "-n", str(installer)], check=True)

    installer_text = installer.read_text()
    assert "UV_LINK_MODE=hardlink" in installer_text
    assert 'uv sync --locked --no-dev --project "$model_dir"' in installer_text

    dockerfile = (root / "Dockerfile").read_text()
    install = "/usr/local/bin/install-asr-model-environments"
    assert dockerfile.count(install) == 2
    assert "rm -rf /home/x/.cache/uv" in dockerfile


def test_image_bundles_only_selected_model_weights() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = root / "install-bundled-model-weights.sh"
    subprocess.run(["bash", "-n", str(installer)], check=True)
    installer_text = installer.read_text()

    for spec in MODELS:
        marker = f"  {spec.id}\n"
        assert (marker in installer_text) == (spec.id in BUNDLED_MODELS)

    dockerfile = (root / "Dockerfile").read_text()
    install = "/usr/local/bin/install-asr-bundled-model-weights"
    assert dockerfile.count(install) == 2
    assert "type=secret,id=huggingface_token" in dockerfile
    assert "HF_TOKEN_PATH=/run/secrets/huggingface_token" in dockerfile


def test_whisper_download_uses_only_vllm_safetensors() -> None:
    script = (
        Path(__file__).resolve().parents[1] / "models/whisper-large-v3/download_model.sh"
    ).read_text()
    assert "--include 'model.safetensors'" in script
    for unused in ("*.safetensors", "model.fp32", "pytorch_model", "flax_model"):
        assert unused not in script


def test_funasr_downloads_pass_all_allowlist_patterns_to_legacy_hf_cli() -> None:
    root = Path(__file__).resolve().parents[1] / "models"
    for model in ("paraformer", "sensevoice"):
        script = (root / model / "download_model.sh").read_text()
        assert script.count("--include") == 1


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
