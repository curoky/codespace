import httpx2

from models.vllm import transcribe
from protocol import InferenceRequest, InferenceResult


async def infer(http: httpx2.AsyncClient, url: str, request: InferenceRequest) -> InferenceResult:
    # 440 给 448-token decoder 的任务控制 token 留余量；complete 拒绝截断响应。
    # helper 固定中文 transcription，避免触发翻译。
    return await transcribe(http, url, request, model="whisper-large-v3", max_completion_tokens=440)
