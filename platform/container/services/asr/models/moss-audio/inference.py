import asyncio
import base64
from pathlib import Path

import httpx2
from pydantic import JsonValue

from models.vllm import EventSourceContext, GenerationOptions, complete_with_generation_retry
from protocol import InferenceRequest, InferenceResult


async def infer(http: httpx2.AsyncClient, url: str, request: InferenceRequest) -> InferenceResult:
    if request.audio is None:
        raise ValueError("audio required")
    audio = base64.b64encode(await asyncio.to_thread(Path(request.audio).read_bytes)).decode()
    content: list[JsonValue] = [
        {"type": "input_audio", "input_audio": {"data": audio, "format": "wav"}}
    ]
    # 复核必须重新听原音，不提供候选答案；通用音频模型可能把口语改写得更流畅。
    content.append(
        {
            "type": "text",
            "text": "请逐字转写这段录音中的话，保留重复、语气词和英文，只输出原话，不做总结。",
        }
    )

    def source(options: GenerationOptions) -> EventSourceContext:
        payload: dict[str, JsonValue] = {
            "model": "moss-audio",
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "seed": 0,
            "max_tokens": 512,
            "stream": True,
        }
        payload.update(options)
        return http.sse(
            url + "/v1/chat/completions",
            method="POST",
            json=payload,
            timeout=1800,
        )

    return await complete_with_generation_retry(source)
