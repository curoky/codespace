from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from protocol import Record


class ResourceConfig(Record):
    gpu_pool: Literal["visible"] | list[str] = "visible"
    wait_seconds: int = Field(default=3600, ge=1)


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
    resources: ResourceConfig = Field(default_factory=ResourceConfig)
    cpu_requests: int = Field(default=2, ge=1)
    chunking: ChunkConfig = Field(default_factory=ChunkConfig)
    punctuation: bool = True


def read_config(path: Path) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text()))
