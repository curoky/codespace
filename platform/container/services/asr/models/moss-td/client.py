import asyncio
import re
from pathlib import Path

import httpx

from models.vllm import complete
from protocol import InferenceRequest, InferenceResult, Span

URL = "http://127.0.0.1:8004"


async def infer(http: httpx.AsyncClient, request: InferenceRequest) -> InferenceResult:
    if request.audio is None:
        raise ValueError("audio required")
    audio = await asyncio.to_thread(Path(request.audio).read_bytes)
    # 结构化时间和 speaker 需要额外输出预算；不能截断后当成完整文稿。
    data = {
        "model": "moss-td",
        "temperature": "0",
        "seed": "0",
        "stream": "true",
        "max_completion_tokens": "8192",
    }
    async with http.stream(
        "POST",
        URL + "/v1/audio/transcriptions",
        data=data,
        files={"file": ("audio.wav", audio, "audio/wav")},
        timeout=1800,
    ) as response:
        result = await complete(response)
    result.spans = parse(result.text)
    return result


def parse(text: str) -> list[Span]:
    # 窗口内 Sxx 需由上层映射为全文件身份，不能直接跨窗口拼接。
    pattern = re.compile(r"\[(\d+(?:\.\d+)?)\]\[(S\d+)\](.*?)\[(\d+(?:\.\d+)?)\]", re.S)
    matches = list(pattern.finditer(text))
    if not matches or pattern.sub("", text).strip():
        raise ValueError("MOSS-TD returned an incomplete structured transcript")
    return [
        Span(
            start_ms=round(float(m[1]) * 1000),
            end_ms=round(float(m[4]) * 1000),
            text=m[3],
            speaker=m[2],
        )
        for m in matches
    ]
