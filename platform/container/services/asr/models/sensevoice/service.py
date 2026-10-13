import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException

from protocol import InferenceRequest, InferenceResult


def app() -> FastAPI:
    from funasr import AutoModel

    weights = Path(__file__).resolve().parent / "weights"
    # cuda:0 是分配给本进程的第一张卡；不配置隐式 VAD、标点或 speaker pipeline。
    # 使用锁定的 FunASR 内建实现，禁止启动时联网更新或加载远程代码。
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
    def transcribe(request: InferenceRequest) -> InferenceResult:
        if request.audio is None:
            raise HTTPException(422, "audio is required")
        path = Path(request.audio).resolve()
        if not path.is_relative_to(Path("/data/asr")) or not path.is_file():
            raise HTTPException(422, "audio must be a file inside /data/asr")
        with lock:
            # 每请求新建 cache；关闭 ITN，避免数字规范化掩盖跨模型分歧。
            # 情绪、语言和事件 tags 保留在 raw，上层比较时才剥离。
            result = model.generate(input=str(path), cache={}, language="zh", use_itn=False)[0]
            return InferenceResult(text=result["text"], raw=result)

    return service
