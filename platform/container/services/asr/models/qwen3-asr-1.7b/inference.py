import httpx2

from models.vllm import transcribe
from protocol import InferenceRequest, InferenceResult


async def infer(http: httpx2.AsyncClient, url: str, request: InferenceRequest) -> InferenceResult:
    # 仅传用户词表，不把其他模型答案作为提示或多计一份家族证据。
    return await transcribe(
        http,
        url,
        request,
        model="qwen3-asr-1.7b",
        max_completion_tokens=512,
        use_hotwords=True,
    )
