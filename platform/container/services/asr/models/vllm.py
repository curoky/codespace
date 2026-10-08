import httpx2
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


async def complete(source: httpx2.EventSource) -> InferenceResult:
    """聚合 vLLM 的标准 SSE 流，只接受显式完成且未被截断的生成。"""
    source.response.raise_for_status()
    text_parts = []
    finishes = []
    ended = False
    async for message in source:
        if message.data == "[DONE]":
            ended = True
            break
        event = Event.model_validate_json(message.data)
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
