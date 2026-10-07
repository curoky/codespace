import httpx

from protocol import InferenceRequest, InferenceResult

URL = "http://127.0.0.1:8010"


async def infer(http: httpx.AsyncClient, request: InferenceRequest) -> InferenceResult:
    response = await http.post(
        URL + "/transcribe",
        json=request.model_dump(mode="json"),
        timeout=1800,
    )
    response.raise_for_status()
    return InferenceResult.model_validate_json(response.content)
