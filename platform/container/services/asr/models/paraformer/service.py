import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException

from protocol import InferenceRequest, InferenceResult


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
    def infer(request: InferenceRequest) -> InferenceResult:
        if request.audio is None:
            raise HTTPException(422, "audio is required")
        audio_path = Path(request.audio).resolve()
        if not audio_path.is_relative_to(Path("/data/asr").resolve()) or not audio_path.is_file():
            raise HTTPException(422, "audio must be a file inside /data/asr")
        with lock:
            # 文件请求之间不共享流式 cache。
            result = model.generate(input=request.audio, cache={})[0]
            return InferenceResult(text=result["text"], raw=result)

    return service
