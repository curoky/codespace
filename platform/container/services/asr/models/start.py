import json
import signal
import subprocess
from pathlib import Path


def main() -> None:
    ports = {
        "firered-llm": 8000,
        "firered-punc": 8001,
        "firered-vad": 8002,
        "moss-audio": 8003,
        "moss-td": 8004,
        "nemotron-diarization": 8005,
        "paraformer": 8006,
        "pyannote-community-1": 8007,
        "qwen3-aligner": 8008,
        "qwen3-asr-1.7b": 8009,
        "sensevoice": 8010,
        "vibevoice": 8011,
        "whisper-large-v3": 8012,
    }
    selected = list(
        dict.fromkeys(
            Path("/run/s6/container_environment/ASR_MODELS").read_text().strip().split(",")
        )
    )
    placement_path = Path("/run/s6/container_environment/ASR_PLACEMENT")
    placement = json.loads(placement_path.read_text() if placement_path.exists() else "{}")
    for model in selected:
        if model not in ports:
            raise ValueError(f"unknown model: {model}")
        if model not in {"firered-punc", "firered-vad"} and not placement.get(model):
            raise ValueError(f"GPU placement is required: {model}")
    services = []
    for model in selected:
        directory = Path("/run/asr") / model
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "PORT").write_text(str(ports[model]))
        if model in placement:
            (directory / "CUDA_VISIBLE_DEVICES").write_text(",".join(map(str, placement[model])))
        services.append("asr-" + model)
    subprocess.run(["/usr/local/bin/s6-rc", "-b", "-u", "change", *services], check=True)  # noqa: S603 - model names validated by ports mapping
    signal.pause()


if __name__ == "__main__":
    main()
