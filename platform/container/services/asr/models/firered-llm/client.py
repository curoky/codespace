import asyncio
from pathlib import Path

import httpx

from models.vllm import complete
from protocol import InferenceRequest, InferenceResult

URL = "http://127.0.0.1:8000"


async def infer(http: httpx.AsyncClient, request: InferenceRequest) -> InferenceResult:
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
    async with http.stream(
        "POST",
        URL + "/v1/audio/transcriptions",
        data=data,
        files={"file": ("audio.wav", audio, "audio/wav")},
        timeout=1800,
    ) as response:
        result = await complete(response)
    return result
