from pathlib import Path

import yaml
from pydantic import Field, model_validator

from protocol import Record


class ResourceConfig(Record):
    gpu_memory_gib: int = Field(ge=1)
    placement: dict[str, list[int]]


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
    resources: ResourceConfig
    cpu_requests: int = Field(default=2, ge=1)
    chunking: ChunkConfig = Field(default_factory=ChunkConfig)
    punctuation: bool = True


def read_config(path: Path) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text()))
