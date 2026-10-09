import asyncio
from pathlib import Path

import httpx2

from models.vllm import EventSourceContext, GenerationOptions, complete_with_generation_retry
from protocol import InferenceRequest, InferenceResult


async def infer(http: httpx2.AsyncClient, url: str, request: InferenceRequest) -> InferenceResult:
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

    def source(options: GenerationOptions) -> EventSourceContext:
        request = dict(data)
        request.update({key: str(value) for key, value in options.items()})
        return http.sse(
            url + "/v1/audio/transcriptions",
            method="POST",
            data=request,
            files={"file": ("audio.wav", audio, "audio/wav")},
            timeout=1800,
        )

    return await complete_with_generation_retry(source)
