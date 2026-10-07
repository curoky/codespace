import asyncio
import base64
from pathlib import Path

import httpx
from pydantic import Field, JsonValue, TypeAdapter

from models.vllm import complete
from protocol import InferenceRequest, InferenceResult, Record, Span

URL = "http://127.0.0.1:8011"


async def infer(http: httpx.AsyncClient, request: InferenceRequest) -> InferenceResult:
    if request.audio is None:
        raise ValueError("audio required")
    audio = base64.b64encode(await asyncio.to_thread(Path(request.audio).read_bytes)).decode()
    content: list[JsonValue] = [
        {"type": "input_audio", "input_audio": {"data": audio, "format": "wav"}}
    ]
    if request.hotwords:
        content.append({"type": "text", "text": "参考词汇：" + "、".join(request.hotwords)})
    # 原生 HF 模型走 audio chat；8192 为时间、speaker 和正文留输出预算。
    async with http.stream(
        "POST",
        URL + "/v1/chat/completions",
        json={
            "model": "vibevoice",
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "seed": 0,
            "max_tokens": 8192,
            "stream": True,
        },
        timeout=1800,
    ) as response:
        result = await complete(response)
    result.spans = parse(result.text)
    return result


# 上游字段区分大小写；speaker 是窗口内标签，跨窗身份映射由上层完成。
class VibeSegment(Record):
    start: float = Field(alias="Start", ge=0)
    end: float = Field(alias="End", ge=0)
    speaker: int = Field(alias="Speaker", ge=0)
    content: str = Field(alias="Content")


def parse(text: str) -> list[Span]:
    payload = text.strip()
    if payload.startswith("```json\n") and payload.endswith("```"):
        payload = payload[8:-3]
    segments = TypeAdapter(list[VibeSegment]).validate_json(payload)
    return [
        Span(
            start_ms=round(s.start * 1000),
            end_ms=round(s.end * 1000),
            speaker=str(s.speaker),
            text=s.content,
        )
        for s in segments
    ]
