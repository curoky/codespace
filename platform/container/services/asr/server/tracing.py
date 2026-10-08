import time
from typing import Literal

from pydantic import Field, JsonValue

from protocol import Record


class TraceEvent(Record):
    kind: Literal["phase", "model"]
    name: str
    channel: str | None = None
    status: Literal["completed", "failed"]
    started_ms: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    model: str | None = None
    cache_hit: bool | None = None
    gpu_ids: list[str] = Field(default_factory=list)
    gpu_indices: list[str] = Field(default_factory=list)
    model_queue_ms: int | None = Field(default=None, ge=0)
    gpu_queue_ms: int | None = Field(default=None, ge=0)
    startup_ms: int | None = Field(default=None, ge=0)
    cpu_queue_ms: int | None = Field(default=None, ge=0)
    inference_ms: int | None = Field(default=None, ge=0)
    input_summary: dict[str, JsonValue] = Field(default_factory=dict)
    output_summary: dict[str, JsonValue] = Field(default_factory=dict)
    error: str | None = None


class TraceDocument(Record):
    schema_version: Literal[1] = 1
    status: Literal["completed", "partial"]
    duration_ms: int = Field(ge=0)
    events: list[TraceEvent]


class Trace:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.events: list[TraceEvent] = []

    @staticmethod
    def begin() -> float:
        return time.monotonic()

    @staticmethod
    def milliseconds(seconds: float) -> int:
        return max(0, round(seconds * 1000))

    def add(
        self,
        *,
        kind: Literal["phase", "model"],
        name: str,
        started: float,
        status: Literal["completed", "failed"],
        channel: str | None = None,
        model: str | None = None,
        cache_hit: bool | None = None,
        gpu_ids: list[str] | None = None,
        gpu_indices: list[str] | None = None,
        model_queue_seconds: float | None = None,
        gpu_queue_seconds: float | None = None,
        startup_seconds: float | None = None,
        cpu_queue_seconds: float | None = None,
        inference_seconds: float | None = None,
        input_summary: dict[str, JsonValue] | None = None,
        output_summary: dict[str, JsonValue] | None = None,
        error: str | None = None,
    ) -> None:
        optional_times = {
            "model_queue_ms": model_queue_seconds,
            "gpu_queue_ms": gpu_queue_seconds,
            "startup_ms": startup_seconds,
            "cpu_queue_ms": cpu_queue_seconds,
            "inference_ms": inference_seconds,
        }
        self.events.append(
            TraceEvent(
                kind=kind,
                name=name,
                channel=channel,
                status=status,
                started_ms=self.milliseconds(started - self.started),
                duration_ms=self.milliseconds(time.monotonic() - started),
                model=model,
                cache_hit=cache_hit,
                gpu_ids=gpu_ids or [],
                gpu_indices=gpu_indices or [],
                input_summary=input_summary or {},
                output_summary=output_summary or {},
                error=error,
                **{
                    key: self.milliseconds(value)
                    for key, value in optional_times.items()
                    if value is not None
                },
            )
        )

    def document(self, status: Literal["completed", "partial"]) -> TraceDocument:
        return TraceDocument(
            status=status,
            duration_ms=self.milliseconds(time.monotonic() - self.started),
            events=sorted(self.events, key=lambda event: event.started_ms),
        )
