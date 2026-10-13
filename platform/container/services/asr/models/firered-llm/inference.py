import httpx2

from models.vllm import transcribe
from protocol import InferenceRequest, InferenceResult


async def infer(http: httpx2.AsyncClient, url: str, request: InferenceRequest) -> InferenceResult:
    # 30 秒输入的 512-token 上限足以容纳逐字转写；循环生成由流式检测立即取消并重试。
    return await transcribe(http, url, request, model="firered-llm", max_completion_tokens=512)
