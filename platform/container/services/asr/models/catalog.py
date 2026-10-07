from pydantic import Field

from protocol import Record


class Resources(Record):
    gpus: int = 1
    memory_gib: float = 12
    startup_seconds: int = 900
    request_seconds: int = 1800


class ModelSpec(Record):
    id: str
    family: str
    role: str
    backend: str
    protocol: str
    resources: Resources = Field(default_factory=Resources)
    max_audio_seconds: int = 30
    language: str | None = "zh"
    hotwords: bool = False
    num_speakers: bool = False


MODELS = [
    ModelSpec(
        id="firered-llm",
        family="firered",
        role="asr",
        backend="vllm",
        protocol="transcription",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        language="",
        resources=Resources(gpus=2, memory_gib=32),
    ),
    ModelSpec(
        id="firered-punc",
        family="firered",
        role="punctuate",
        backend="sdk",
        protocol="sdk-http",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        language=None,
        resources=Resources(gpus=0, memory_gib=0),
    ),
    ModelSpec(
        id="firered-vad",
        family="firered",
        role="vad",
        backend="sdk",
        protocol="sdk-http",
        max_audio_seconds=86400,
        hotwords=False,
        num_speakers=False,
        language=None,
        resources=Resources(gpus=0, memory_gib=0),
    ),
    ModelSpec(
        id="moss-audio",
        family="moss-audio",
        role="review",
        backend="vllm",
        protocol="chat",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        language=None,
        resources=Resources(gpus=1, memory_gib=32),
    ),
    ModelSpec(
        id="moss-td",
        family="moss-td",
        role="joint",
        backend="vllm",
        protocol="transcription",
        max_audio_seconds=180,
        hotwords=False,
        num_speakers=False,
        language=None,
        resources=Resources(gpus=1, memory_gib=48),
    ),
    ModelSpec(
        id="nemotron-diarization",
        family="nemotron",
        role="diarize",
        backend="sdk",
        protocol="sdk-http",
        max_audio_seconds=86400,
        hotwords=False,
        num_speakers=False,
        language=None,
        resources=Resources(gpus=1, memory_gib=12),
    ),
    ModelSpec(
        id="paraformer",
        family="paraformer",
        role="asr",
        backend="sdk",
        protocol="sdk-http",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        language="zh",
        resources=Resources(gpus=1, memory_gib=4),
    ),
    ModelSpec(
        id="pyannote-community-1",
        family="pyannote",
        role="diarize",
        backend="sdk",
        protocol="sdk-http",
        max_audio_seconds=86400,
        hotwords=False,
        num_speakers=True,
        language=None,
        resources=Resources(gpus=1, memory_gib=6),
    ),
    ModelSpec(
        id="qwen3-aligner",
        family="qwen",
        role="align",
        backend="vllm-pooling",
        protocol="sdk-http",
        max_audio_seconds=300,
        hotwords=False,
        num_speakers=False,
        language=None,
        resources=Resources(gpus=1, memory_gib=8),
    ),
    ModelSpec(
        id="qwen3-asr-1.7b",
        family="qwen",
        role="asr",
        backend="vllm",
        protocol="transcription",
        max_audio_seconds=30,
        hotwords=True,
        num_speakers=False,
        language="zh",
        resources=Resources(gpus=1, memory_gib=12),
    ),
    ModelSpec(
        id="sensevoice",
        family="sensevoice",
        role="asr",
        backend="sdk",
        protocol="sdk-http",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        language="zh",
        resources=Resources(gpus=1, memory_gib=4),
    ),
    ModelSpec(
        id="vibevoice",
        family="vibevoice",
        role="joint",
        backend="vllm",
        protocol="chat",
        max_audio_seconds=180,
        hotwords=True,
        num_speakers=False,
        language=None,
        resources=Resources(gpus=1, memory_gib=48),
    ),
    ModelSpec(
        id="whisper-large-v3",
        family="whisper",
        role="asr",
        backend="vllm",
        protocol="transcription",
        max_audio_seconds=30,
        hotwords=False,
        num_speakers=False,
        language="zh",
        resources=Resources(gpus=1, memory_gib=8),
    ),
]
