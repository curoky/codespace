import asyncio
from pathlib import Path

import httpx2

from models.vllm import complete
from protocol import InferenceRequest, InferenceResult


async def infer(http: httpx2.AsyncClient, url: str, request: InferenceRequest) -> InferenceResult:
    if request.audio is None:
        raise ValueError("audio required")
    audio = await asyncio.to_thread(Path(request.audio).read_bytes)
    # 2048 限制重复生成，截断视为失败；FireRed 默认语言是英文，中文流程必须显式指定 zh。
    data = {
        "model": "firered-llm",
        "language": "zh",
        "temperature": "0",
        "seed": "0",
        "stream": "true",
        "max_completion_tokens": "2048",
    }
    async with http.sse(
        url + "/v1/audio/transcriptions",
        method="POST",
        data=data,
        files={"file": ("audio.wav", audio, "audio/wav")},
        timeout=1800,
    ) as source:
        result = await complete(source)
    return result
