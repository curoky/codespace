from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from protocol import Record


class ResourceConfig(Record):
    gpu_pool: Literal["visible"] | list[str] = "visible"
    exclusive_gpu: Literal[True] = True
    wait_seconds: int = Field(default=3600, ge=1)


class ParallelConfig(Record):
    active_files: int = Field(default=2, ge=1)
    cpu_requests: int = Field(default=2, ge=1)


class ChunkConfig(Record):
    target_seconds: int = Field(default=24, ge=1)
    max_seconds: int = Field(default=30, ge=1)
    padding_ms: int = Field(default=300, ge=0)

    @model_validator(mode="after")
    def bounded(self) -> "ChunkConfig":
        if self.target_seconds * 1000 + 2 * self.padding_ms > self.max_seconds * 1000:
            raise ValueError("target plus padding exceeds max_seconds")
        return self


class Config(Record):
    suite: Literal["all"] = "all"
    data_dir: Path = Path("/data/asr")
    models_dir: Path = Path("/opt/asr/models")
    runtime_dir: Path = Path("/run/asr")
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    parallel: ParallelConfig = Field(default_factory=ParallelConfig)
    chunking: ChunkConfig = Field(default_factory=ChunkConfig)
    vad: tuple[Literal["firered-vad"], ...] = ("firered-vad",)
    aligner: Literal["qwen3-aligner"] = "qwen3-aligner"
    punctuation: Literal["firered-punc"] | None = "firered-punc"
    diarizer: Literal["pyannote-community-1"] = "pyannote-community-1"
    max_upload_bytes: int = Field(default=20 * 1024**3, ge=1)


def read_config(path: Path) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text()))
