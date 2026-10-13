import threading
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile

from models.audio import evidence, uploaded
from protocol import InferenceResult


def app() -> FastAPI:
    from funasr import AutoModel

    weights = Path(__file__).resolve().parent / "weights"
    # cuda:0 是进程内可见设备；不配置隐式 VAD、标点或 speaker pipeline。
    # 禁止自动更新；普通 checkpoint 不传动态热词，避免按 SeACo 的能力调用。
    model = AutoModel(
        model=str(weights),
        device="cuda:0",
        disable_update=True,
        disable_log=True,
        trust_remote_code=False,
    )
    service = FastAPI(docs_url=None, redoc_url=None)
    lock = threading.Lock()

    @service.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @service.post("/transcribe")
    def transcribe(file: UploadFile | None = None, options: str = Form("{}")) -> InferenceResult:
        with uploaded(file, options) as request:
            if request.mode not in {"verbatim", "narration", "conversation", "meeting"}:
                raise HTTPException(422, "unsupported inference mode")
            if request.audio is None:
                raise HTTPException(422, "audio is required")
            path = Path(request.audio).resolve()
            with lock:
                # 文件请求之间不共享流式 cache。
                result = model.generate(input=str(path), cache={})[0]
                result_record = InferenceResult(text=result["text"], raw=result)
                return evidence(result_record, request, Path(__file__).resolve().parent)

    return service
