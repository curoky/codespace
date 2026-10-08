import asyncio
from pathlib import Path

import httpx2

from models.vllm import complete
from protocol import InferenceRequest, InferenceResult

URL = "http://127.0.0.1:8009"


async def infer(http: httpx2.AsyncClient, request: InferenceRequest) -> InferenceResult:
    if request.audio is None:
        raise ValueError("audio required")
    audio = await asyncio.to_thread(Path(request.audio).read_bytes)
    data = {
        "model": "qwen3-asr-1.7b",
        "temperature": "0",
        "seed": "0",
        "stream": "true",
        "max_completion_tokens": "2048",
    }
    data["language"] = "zh"
    # 仅传用户词表，不把其他模型答案作为提示或多计一份家族证据。
    if request.hotwords:
        data["hotwords"] = ",".join(request.hotwords)
    async with http.sse(
        URL + "/v1/audio/transcriptions",
        method="POST",
        data=data,
        files={"file": ("audio.wav", audio, "audio/wav")},
        timeout=1800,
    ) as source:
        result = await complete(source)
    return result
