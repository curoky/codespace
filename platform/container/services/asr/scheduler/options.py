from typing import Literal

from pydantic import Field

from protocol import Record


class Options(Record):
    scenario: Literal["narration", "conversation", "conversation_tracks", "meeting"]
    recipes: list[str] = Field(default_factory=list)
    num_speakers: int | None = None
    hotwords: list[str] = Field(default_factory=list)
    language: str = "zh"
