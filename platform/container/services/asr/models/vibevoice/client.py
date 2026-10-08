import asyncio
import base64
import wave
from pathlib import Path

import httpx2
from pydantic import Field, JsonValue, TypeAdapter

from models.vllm import complete
from protocol import InferenceRequest, InferenceResult, Record, Span

URL = "http://127.0.0.1:8011"


def duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


async def infer(http: httpx2.AsyncClient, request: InferenceRequest) -> InferenceResult:
    if request.audio is None:
        raise ValueError("audio required")
    path = Path(request.audio)
    audio = base64.b64encode(await asyncio.to_thread(path.read_bytes)).decode()
    seconds = await asyncio.to_thread(duration, path)
    content: list[JsonValue] = [
        {"type": "audio_url", "audio_url": {"url": "data:audio/wav;base64," + audio}},
    ]
    if request.hotwords:
        content.append({"type": "text", "text": "、".join(request.hotwords)})
    # vLLM 不会替换 HF 模板中的时长占位符；由固定服务端模板接收实际时长。
    async with http.sse(
        URL + "/v1/chat/completions",
        method="POST",
        json={
            "model": "vibevoice",
            "messages": [{"role": "user", "content": content}],
            "chat_template_kwargs": {"audio_duration": f"{seconds:.2f}"},
            "temperature": 0,
            "top_p": 1,
            "max_tokens": 32768,
            "stream": True,
        },
        timeout=1800,
    ) as source:
        result = await complete(source)
    result.spans = parse(result.text)
    return result


# 上游字段区分大小写；speaker 是窗口内标签，跨窗身份映射由上层完成。
class VibeSegment(Record):
    start: float = Field(alias="Start", ge=0)
    end: float = Field(alias="End", ge=0)
    speaker: int | None = Field(default=None, alias="Speaker", ge=0)
    content: str = Field(alias="Content")


def parse(text: str) -> list[Span]:
    payload = text.strip()
    # Checkpoint 原生模板停在 user turn，模型会自行生成固定的纯文本 role header。
    if payload.startswith("assistant\n"):
        payload = payload.removeprefix("assistant\n").lstrip()
    if payload.startswith("```json\n") and payload.endswith("```"):
        payload = payload[8:-3]
    segments = TypeAdapter(list[VibeSegment]).validate_json(payload)
    return [
        Span(
            start_ms=round(s.start * 1000),
            end_ms=round(s.end * 1000),
            speaker=str(s.speaker) if s.speaker is not None else None,
            text=s.content,
        )
        for s in segments
        if s.content.strip() != "[Silence]"
    ]
