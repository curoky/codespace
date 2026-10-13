import time

from pydantic import Field, JsonValue

from protocol import Record


class TraceEvent(Record):
    kind: str
    name: str
    recipe: str = ""
    channel: str | None = None
    status: str = "completed"
    started_ms: int
    duration_ms: int
    model: str | None = None
    model_queue_ms: int = 0
    inference_ms: int = 0
    input_summary: dict[str, JsonValue] = Field(default_factory=dict)
    output_summary: dict[str, JsonValue] = Field(default_factory=dict)


class Trace:
    def __init__(self) -> None:
        self.started = time.monotonic()
        self.events: list[TraceEvent] = []

    def add(
        self,
        *,
        kind: str,
        name: str,
        started: float,
        recipe: str = "",
        channel: str | None = None,
        model: str | None = None,
        model_queue_ms: int = 0,
        inference_ms: int = 0,
        input_summary: dict[str, JsonValue] | None = None,
        output_summary: dict[str, JsonValue] | None = None,
    ) -> None:
        self.events.append(
            TraceEvent(
                kind=kind,
                name=name,
                recipe=recipe,
                channel=channel,
                model=model,
                started_ms=round((started - self.started) * 1000),
                duration_ms=round((time.monotonic() - started) * 1000),
                model_queue_ms=model_queue_ms,
                inference_ms=inference_ms,
                input_summary=input_summary or {},
                output_summary=output_summary or {},
            )
        )

    def document(self) -> dict[str, JsonValue]:
        return {
            "schema_version": 3,
            "status": "completed",
            "duration_ms": round((time.monotonic() - self.started) * 1000),
            "events": [event.model_dump(mode="json") for event in self.events],
        }
