from pathlib import Path

import yaml
from pydantic import Field

from protocol import Record


class Instance(Record):
    model: str
    url: str
    capacity: int = Field(default=1, ge=1)


class Config(Record):
    instances: list[Instance]
    cpu_requests: int = Field(default=4, ge=1)


class ChunkConfig(Record):
    target_seconds: int = 24
    padding_ms: int = 300


def read_config(path: Path) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text()))
