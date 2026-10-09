from pathlib import Path

import yaml
from pydantic import Field, model_validator

from protocol import Record


class ModelInstanceConfig(Record):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]*$")
    model: str
    port: int = Field(ge=1, le=65535)
    placement: list[int] = Field(default_factory=list)


class ResourceConfig(Record):
    gpu_memory_gib: int = Field(ge=1)
    instances: list[ModelInstanceConfig]

    @model_validator(mode="after")
    def unique_instances(self) -> "ResourceConfig":
        ids = [instance.id for instance in self.instances]
        ports = [instance.port for instance in self.instances]
        if len(ids) != len(set(ids)):
            raise ValueError("instance ids must be unique")
        if len(ports) != len(set(ports)):
            raise ValueError("instance ports must be unique")
        return self


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
