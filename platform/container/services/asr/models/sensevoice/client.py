import httpx2

from protocol import InferenceRequest, InferenceResult


async def infer(http: httpx2.AsyncClient, url: str, request: InferenceRequest) -> InferenceResult:
    response = await http.post(
        url + "/transcribe",
        json=request.model_dump(mode="json"),
        timeout=1800,
    )
    response.raise_for_status()
    return InferenceResult.model_validate_json(response.content)
