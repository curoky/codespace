import asyncio
from pathlib import Path

import httpx

from models.vllm import complete
from protocol import InferenceRequest, InferenceResult

URL = "http://127.0.0.1:8012"


async def infer(http: httpx.AsyncClient, request: InferenceRequest) -> InferenceResult:
    if request.audio is None:
        raise ValueError("audio required")
    audio = await asyncio.to_thread(Path(request.audio).read_bytes)
    # 440 给 448-token decoder 的任务控制 token 留余量；complete 拒绝截断响应。
    data = {
        "model": "whisper-large-v3",
        "temperature": "0",
        "seed": "0",
        "stream": "true",
        "max_completion_tokens": "440",
    }
    # 固定中文 transcription，避免触发翻译。
    data["language"] = "zh"
    async with http.stream(
        "POST",
        URL + "/v1/audio/transcriptions",
        data=data,
        files={"file": ("audio.wav", audio, "audio/wav")},
        timeout=1800,
    ) as response:
        result = await complete(response)
    return result
