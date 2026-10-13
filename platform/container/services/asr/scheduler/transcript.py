from pydantic import Field

from protocol import Record, Span, Token


class Segment(Record):
    channel: int | None = None
    start_ms: int
    end_ms: int
    text: str
    speakers: list[str] = Field(default_factory=list)
    tokens: list[Token] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    candidates: dict[str, str] = Field(default_factory=dict)
    reviews: dict[str, str] = Field(default_factory=dict)
    decision: str = "primary"


class Transcript(Record):
    recipe: str
    status: str = "completed"
    error: str | None = None
    segments: list[Segment] = Field(default_factory=list)
    activity: list[Span] = Field(default_factory=list)
    speakers: list[Span] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
