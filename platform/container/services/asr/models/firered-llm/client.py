import asyncio
from pathlib import Path

import httpx2

from models.vllm import EventSourceContext, GenerationOptions, complete_with_generation_retry
from protocol import InferenceRequest, InferenceResult


async def infer(http: httpx2.AsyncClient, url: str, request: InferenceRequest) -> InferenceResult:
    if request.audio is None:
        raise ValueError("audio required")
    audio = await asyncio.to_thread(Path(request.audio).read_bytes)
    # 30 秒输入的 512-token 上限足以容纳逐字转写；循环生成由流式检测立即取消并重试。
    data = {
        "model": "firered-llm",
        "language": "zh",
        "temperature": "0",
        "seed": "0",
        "stream": "true",
        "max_completion_tokens": "512",
    }

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
