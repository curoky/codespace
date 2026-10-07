from pydantic import Field

from protocol import Record


class Resources(Record):
    gpus: int = 1
    memory_gib: float = 12
    startup_seconds: int = 900


class ModelSpec(Record):
    id: str
    family: str
    resources: Resources = Field(default_factory=Resources)
    max_audio_seconds: int = 30
    hotwords: bool = False
    num_speakers: bool = False


MODELS = [
    ModelSpec(
        id="firered-llm",
        family="firered",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        resources=Resources(gpus=2, memory_gib=32),
    ),
    ModelSpec(
        id="firered-punc",
        family="firered",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        resources=Resources(gpus=0, memory_gib=0),
    ),
    ModelSpec(
        id="firered-vad",
        family="firered",
        max_audio_seconds=86400,
        hotwords=False,
        num_speakers=False,
        resources=Resources(gpus=0, memory_gib=0),
    ),
    ModelSpec(
        id="moss-audio",
        family="moss-audio",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        resources=Resources(gpus=1, memory_gib=32),
    ),
    ModelSpec(
        id="moss-td",
        family="moss-td",
        max_audio_seconds=180,
        hotwords=False,
        num_speakers=False,
        resources=Resources(gpus=1, memory_gib=48),
    ),
    ModelSpec(
        id="nemotron-diarization",
        family="nemotron",
        max_audio_seconds=86400,
        hotwords=False,
        num_speakers=False,
        resources=Resources(gpus=1, memory_gib=12),
    ),
    ModelSpec(
        id="paraformer",
        family="paraformer",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        resources=Resources(gpus=1, memory_gib=4),
    ),
    ModelSpec(
        id="pyannote-community-1",
        family="pyannote",
        max_audio_seconds=86400,
        hotwords=False,
        num_speakers=True,
        resources=Resources(gpus=1, memory_gib=6),
    ),
    ModelSpec(
        id="qwen3-aligner",
        family="qwen",
        max_audio_seconds=300,
        hotwords=False,
        num_speakers=False,
        resources=Resources(gpus=1, memory_gib=8),
    ),
    ModelSpec(
        id="qwen3-asr-1.7b",
        family="qwen",
        max_audio_seconds=30,
        hotwords=True,
        num_speakers=False,
        resources=Resources(gpus=1, memory_gib=12),
    ),
    ModelSpec(
        id="sensevoice",
        family="sensevoice",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        resources=Resources(gpus=1, memory_gib=4),
    ),
    ModelSpec(
        id="vibevoice",
        family="vibevoice",
        max_audio_seconds=180,
        hotwords=True,
        num_speakers=False,
        resources=Resources(gpus=1, memory_gib=48),
    ),
    ModelSpec(
        id="whisper-large-v3",
        family="whisper",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        resources=Resources(gpus=1, memory_gib=8),
    ),
]
