import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Annotated

import httpx2
from fastapi import FastAPI, Form, UploadFile
from inference import infer

from models.audio import evidence
from models.engine import run
from protocol import InferenceRequest, InferenceResult

service = FastAPI(docs_url=None, redoc_url=None)


@service.get("/health")
async def health() -> dict[str, str]:
    async with httpx2.AsyncClient(trust_env=False) as client:
        response = await client.get(f"http://127.0.0.1:{run.engine_port}/health")
        response.raise_for_status()
    return {"status": "ready"}


@service.post("/transcribe")
async def transcribe(file: UploadFile, options: Annotated[str, Form()] = "{}") -> InferenceResult:
    request = InferenceRequest.model_validate_json(options)
    if request.mode not in {"verbatim", "narration", "conversation", "meeting"}:
        raise ValueError("unsupported inference mode")
    with tempfile.TemporaryDirectory(prefix="inference-", dir="/data/asr") as temporary:
        path = Path(temporary) / "audio.wav"
        with path.open("wb") as target:
            while chunk := await file.read(1024 * 1024):
                await asyncio.to_thread(target.write, chunk)
        request.audio = str(path)
        async with httpx2.AsyncClient(trust_env=False) as client:
            result = await infer(client, f"http://127.0.0.1:{run.engine_port}", request)
        return evidence(result, request, Path(__file__).resolve().parent)


if __name__ == "__main__":
    run(service, sys.argv[1:])
