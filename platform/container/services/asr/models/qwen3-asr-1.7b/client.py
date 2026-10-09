import asyncio
from pathlib import Path

import httpx2

from models.vllm import EventSourceContext, GenerationOptions, complete_with_generation_retry
from protocol import InferenceRequest, InferenceResult


async def infer(http: httpx2.AsyncClient, url: str, request: InferenceRequest) -> InferenceResult:
    if request.audio is None:
        raise ValueError("audio required")
    audio = await asyncio.to_thread(Path(request.audio).read_bytes)
    data = {
        "model": "qwen3-asr-1.7b",
        "temperature": "0",
        "seed": "0",
        "stream": "true",
        "max_completion_tokens": "512",
    }
    data["language"] = "zh"
    # 仅传用户词表，不把其他模型答案作为提示或多计一份家族证据。
    if request.hotwords:
        data["hotwords"] = ",".join(request.hotwords)

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
