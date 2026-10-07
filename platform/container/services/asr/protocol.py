from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Span(Record):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str = ""
    speaker: str | None = None

    @model_validator(mode="after")
    def ordered(self) -> "Span":
        if self.end_ms < self.start_ms:
            raise ValueError("end_ms precedes start_ms")
        return self


class Token(Record):
    text: str
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    speakers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered(self) -> "Token":
        if (self.start_ms is None) != (self.end_ms is None):
            raise ValueError("both timestamps must be present or null")
        if self.start_ms is not None and self.end_ms is not None and self.end_ms < self.start_ms:
            raise ValueError("end_ms precedes start_ms")
        return self


class InferenceRequest(Record):
    audio: str | None = None
    text: str = ""
    hotwords: list[str] = Field(default_factory=list)
    num_speakers: int | None = Field(default=None, ge=1)


class InferenceResult(Record):
    text: str = ""
    spans: list[Span] = Field(default_factory=list)
    tokens: list[Token] = Field(default_factory=list)
    raw: JsonValue = None
    warnings: list[str] = Field(default_factory=list)
