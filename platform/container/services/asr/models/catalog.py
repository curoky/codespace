from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    family: str
    gpus: int = 1
    memory_gib: float = 12
    startup_seconds: int = 900
    max_audio_seconds: int = 30
    hotwords: bool = False
    num_speakers: bool = False


MODELS = (
    ModelSpec("firered-llm", "firered", gpus=2, memory_gib=32),
    ModelSpec("firered-punc", "firered", gpus=0, memory_gib=0),
    ModelSpec("firered-vad", "firered", gpus=0, memory_gib=0, max_audio_seconds=86400),
    ModelSpec("moss-audio", "moss-audio", memory_gib=32),
    ModelSpec("moss-td", "moss-td", memory_gib=48, max_audio_seconds=180),
    ModelSpec("nemotron-diarization", "nemotron", max_audio_seconds=86400),
    ModelSpec("paraformer", "paraformer", memory_gib=4),
    ModelSpec(
        "pyannote-community-1",
        "pyannote",
        memory_gib=6,
        max_audio_seconds=86400,
        num_speakers=True,
    ),
    ModelSpec("qwen3-aligner", "qwen", memory_gib=8, max_audio_seconds=300),
    ModelSpec("qwen3-asr-1.7b", "qwen", hotwords=True),
    ModelSpec("sensevoice", "sensevoice", memory_gib=4),
    ModelSpec("vibevoice", "vibevoice", memory_gib=48, max_audio_seconds=180, hotwords=True),
    ModelSpec("whisper-large-v3", "whisper", memory_gib=8),
)
