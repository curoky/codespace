import httpx

from protocol import InferenceRequest, InferenceResult

URL = "http://127.0.0.1:8008"


async def infer(http: httpx.AsyncClient, request: InferenceRequest) -> InferenceResult:
    response = await http.post(
        URL + "/align",
        json=request.model_dump(mode="json"),
        timeout=1800,
    )
    response.raise_for_status()
    return InferenceResult.model_validate_json(response.content)
