import asyncio
import base64
from pathlib import Path

import httpx
from pydantic import JsonValue

from models.vllm import complete
from protocol import InferenceRequest, InferenceResult

URL = "http://127.0.0.1:8003"


async def infer(http: httpx.AsyncClient, request: InferenceRequest) -> InferenceResult:
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
    async with http.stream(
        "POST",
        URL + "/v1/chat/completions",
        json={
            "model": "moss-audio",
            "messages": [{"role": "user", "content": content}],
            "temperature": 0,
            "seed": 0,
            "max_tokens": 2048,
            "stream": True,
        },
        timeout=1800,
    ) as response:
        result = await complete(response)
    return result
