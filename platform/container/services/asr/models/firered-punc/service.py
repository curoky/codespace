import threading
from pathlib import Path

from fastapi import FastAPI

from protocol import InferenceRequest, InferenceResult


def app() -> FastAPI:
    from fireredasr2s.fireredpunc.punc import FireRedPunc, FireRedPuncConfig

    weights = Path(__file__).resolve().parent / "weights"
    # 标点使用 CPU；上层按语音窗口调用，并拒绝任何非标点字符的改写。
    model = FireRedPunc.from_pretrained(str(weights), FireRedPuncConfig(use_gpu=False))

    service = FastAPI(docs_url=None, redoc_url=None)
    lock = threading.Lock()

    @service.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @service.post("/punctuate")
    def infer(request: InferenceRequest) -> InferenceResult:
        with lock:
            result = model.process([request.text])[0]
            return InferenceResult(text=result["punc_text"], raw=result)

    return service
