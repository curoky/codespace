import json
import threading
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile

from models.audio import evidence, uploaded
from protocol import InferenceResult, Span


def app() -> FastAPI:
    from fireredasr2s.fireredvad import FireRedVad, FireRedVadConfig

    weights = Path(__file__).resolve().parent / "weights/VAD"
    # 轻量 VAD 使用 CPU；阈值沿用固定 SDK 默认值，padding 由上层统一处理。
    model = FireRedVad.from_pretrained(str(weights), FireRedVadConfig(use_gpu=False))
    service = FastAPI(docs_url=None, redoc_url=None)
    lock = threading.Lock()

    @service.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @service.post("/vad")
    def detect(file: UploadFile | None = None, options: str = Form("{}")) -> InferenceResult:
        with uploaded(file, options) as request:
            if request.audio is None:
                raise HTTPException(422, "audio is required")
            path = Path(request.audio).resolve()
            with lock:
                # 每次处理完整文件，不能逐短窗重置检测状态。
                result, _ = model.detect(str(path))
                result_record = InferenceResult(
                    spans=[
                        Span(start_ms=round(a * 1000), end_ms=round(b * 1000))
                        for a, b in result["timestamps"]
                    ],
                    raw=json.loads(json.dumps(result)),
                )
                return evidence(result_record, request, Path(__file__).resolve().parent)

    return service
