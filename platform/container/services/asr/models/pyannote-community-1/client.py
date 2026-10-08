import httpx2

from protocol import InferenceRequest, InferenceResult

URL = "http://127.0.0.1:8007"


async def infer(http: httpx2.AsyncClient, request: InferenceRequest) -> InferenceResult:
    response = await http.post(
        URL + "/diarize",
        json=request.model_dump(mode="json"),
        timeout=1800,
    )
    response.raise_for_status()
    return InferenceResult.model_validate_json(response.content)
