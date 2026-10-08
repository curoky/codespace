import ast
import asyncio
import os
import subprocess
from pathlib import Path

import yaml

from models.catalog import MODELS
from ops.scheduler import Scheduler
from server.config import Config, read_config


def config() -> Config:
    return read_config(Path(__file__).resolve().parents[1] / "server/server.yaml")


def test_each_model_has_revisioned_download_and_static_service(tmp_path: Path) -> None:
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
        assert dependency.is_file()
        download_up = (download / "up").read_text()
        assert "download_model.sh" in download_up
        assert "HF_TOKEN_PATH=/run/secrets/huggingface_token" in download_up
        download_script = (directory / "download_model.sh").read_text()
        assert "hf download" in download_script
        assert "--include" in download_script
        assert "--exclude" not in download_script
        assert "revision=" in download_script
        assert "weights/.revision" in download_script
        assert 'mkdir -p "$(readlink -m -- "$model_dir/weights")"' in download_script
        assert not (directory / "download_model.py").exists()
        for script in (download_script, (directory / "run").read_text()):
            assert "--frozen" in script
            assert "--no-sync" in script
            assert "--locked" not in script

        revision = next(
            line.removeprefix("revision=")
            for line in download_script.splitlines()
            if line.startswith("revision=")
        )
        local_model = tmp_path / spec.id
        (local_model / "weights").mkdir(parents=True)
        (local_model / "weights/.revision").write_text(revision)
        local_script = local_model / "download_model.sh"
        local_script.write_text(download_script)
        subprocess.run(
            ["bash", str(local_script)],
            check=True,
            env={"PATH": "/usr/bin:/bin"},
        )


def test_image_installs_model_environments_in_one_layer() -> None:
    root = Path(__file__).resolve().parents[1]
    installer = root / "install-model-environments.sh"
    subprocess.run(["bash", "-n", str(installer)], check=True)

    installer_text = installer.read_text()
    assert "UV_LINK_MODE=hardlink" in installer_text
    assert "uv sync" in installer_text
    assert '--project "$model_dir"' in installer_text
    for package in (
        "cuda-toolkit",
        "nvidia-cuda-crt",
        "nvidia-cuda-nvcc",
        "nvidia-nvvm",
    ):
        assert f"--no-install-package {package}" in installer_text

    dockerfile = (root / "Dockerfile").read_text()
    assert (
        "nvidia/cuda:13.0.3-devel-ubuntu24.04@sha256:"
        "b7ae301dea2c162444795462ce17a05f6a516e5a75944b57af5b88540a1a2266" in dockerfile
    )
    assert "COPY --from=cuda-toolkit /opt/cuda-13.0/ /usr/local/cuda-13.0/" in dockerfile
    assert "PATH=/usr/local/cuda-13.0/bin:${PATH}" in dockerfile
    install = "/usr/local/bin/install-asr-model-environments"
    deduplicate = "hardlink --ignore-time --respect-xattrs --maximize"
    assert dockerfile.count(install) == 2
    assert dockerfile.count(deduplicate) == 1
    assert "/opt/asr/models/*/.venv /opt/asr/server/.venv" in dockerfile
    assert "rm -rf /home/x/.cache/uv" in dockerfile
    assert (
        dockerfile.index(install, dockerfile.index("RUN export HOME"))
        < dockerfile.index(deduplicate)
        < dockerfile.index("rm -rf /home/x/.cache/uv")
    )


def test_image_contains_no_model_weights() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    assert "install-bundled-model-weights" not in dockerfile
    assert "type=secret" not in dockerfile
    assert "mkdir -p /data/asr /model-data /run/asr" in dockerfile
    assert 'ln -s "/model-data/${model_dir##*/}" "$model_dir/weights"' in dockerfile


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


def test_vllm_transcription_config_is_model_owned() -> None:
    root = Path(__file__).resolve().parents[1] / "models"
    for model in ("firered-llm", "moss-td", "qwen3-asr-1.7b", "whisper-large-v3"):
        assert "--speech-to-text-config" not in (root / model / "run").read_text()


def test_vllm_models_use_global_cuda_toolchain() -> None:
    root = Path(__file__).resolve().parents[1] / "models"
    for model in (
        "firered-llm",
        "moss-audio",
        "moss-td",
        "qwen3-aligner",
        "qwen3-asr-1.7b",
        "vibevoice",
        "whisper-large-v3",
    ):
        run = (root / model / "run").read_text()
        project = (root / model / "pyproject.toml").read_text()
        assert "export CUDA_HOME=/usr/local/cuda-13.0" in run
        assert (
            "export LD_LIBRARY_PATH=/usr/local/cuda-13.0/compat:/usr/local/cuda-13.0/lib64" in run
        )
        assert "cuda-toolkit[nvcc]" not in project


def test_static_placement_uses_five_80_gib_gpus_for_parallel_stages() -> None:
    root = Path(__file__).resolve().parents[1]
    resources = config().resources
    specs = {spec.id: spec for spec in MODELS if spec.gpus}
    assert set(resources.placement) == set(specs)
    loads = [0.0] * 5
    for model, placement in resources.placement.items():
        spec = specs[model]
        assert len(placement) == spec.gpus
        assert len(set(placement)) == len(placement)
        for index in placement:
            loads[index] += spec.memory_gib
    assert resources.gpu_memory_gib == 80
    assert loads == [64, 50, 60, 60, 12]
    assert all(load < resources.gpu_memory_gib for load in loads)

    first_pass = {
        "firered-llm": {0, 1},
        "qwen3-asr-1.7b": {2},
        "sensevoice": {3},
        "paraformer": {4},
    }
    assert len(set().union(*first_pass.values())) == sum(map(len, first_pass.values())) == 5

    utilization = {
        "firered-llm": "0.40",
        "moss-audio": "0.40",
        "moss-td": "0.60",
        "qwen3-asr-1.7b": "0.15",
        "vibevoice": "0.60",
        "whisper-large-v3": "0.10",
    }
    for model, value in utilization.items():
        run = (root / "models" / model / "run").read_text()
        assert f"--gpu-memory-utilization {value}" in run

    aligner = (root / "models/qwen3-aligner/service.py").read_text()
    assert "gpu_memory_utilization=0.10" in aligner


def test_normal_deployment_allocates_shared_memory() -> None:
    example = Path(__file__).resolve().parents[5] / "config.example.yaml"
    config = yaml.safe_load(example.read_text())
    assert config["services"]["asr"]["container"]["shm_size"] == "8g"


def test_model_clients_match_fixed_listeners(tmp_path: Path) -> None:
    uv = tmp_path / "uv"
    uv.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n')
    uv.chmod(0o755)
    scheduler = Scheduler(config())
    try:
        ports = set()
        for instance in scheduler.instances.values():
            directory = Path(__file__).resolve().parents[1] / "models" / instance.spec.id
            result = subprocess.run(
                [str(directory / "run")],
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
            if instance.spec.id == "vibevoice":
                assert args[args.index("--max-model-len") + 1] == "65536"
                template = args[args.index("--chat-template") + 1]
                assert template.endswith("/vibevoice/chat_template.jinja")
                assert "{{ audio_duration }}" in (directory / "chat_template.jinja").read_text()
            assert port not in ports
            ports.add(port)
        assert ports == set(range(8000, 8013))
    finally:
        asyncio.run(scheduler.close())
