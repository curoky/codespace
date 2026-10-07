import httpx
from pydantic import ConfigDict, Field, JsonValue

from protocol import InferenceResult, Record


class Delta(Record):
    model_config = ConfigDict(extra="ignore")
    content: str | None = None


class Choice(Record):
    model_config = ConfigDict(extra="ignore")
    delta: Delta = Field(default_factory=Delta)
    finish_reason: str | None = None


class Event(Record):
    model_config = ConfigDict(extra="ignore")
    choices: list[Choice] = Field(default_factory=list)


async def complete(response: httpx.Response) -> InferenceResult:
    response.raise_for_status()
    text_parts = []
    finishes = []
    ended = False
    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        if line[6:] == "[DONE]":
            ended = True
            break
        event = Event.model_validate_json(line[6:])
        for choice in event.choices:
            if choice.delta.content:
                text_parts.append(choice.delta.content)
            if choice.finish_reason:
                finishes.append(choice.finish_reason)
    if not ended or not finishes or any(reason != "stop" for reason in finishes):
        raise ValueError(f"incomplete generation ({finishes})")
    text = "".join(text_parts)
    return InferenceResult(
        text=text, raw={"text": text, "finish_reasons": list[JsonValue](finishes)}
    )
