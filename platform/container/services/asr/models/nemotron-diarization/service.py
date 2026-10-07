import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException

from protocol import InferenceRequest, InferenceResult, Span


def app() -> FastAPI:
    import soundfile as sf
    from nemo.collections.asr.models import SortformerEncLabelModel

    weights = Path(__file__).resolve().parent / "weights"
    checkpoints = list(weights.glob("*.nemo"))
    if len(checkpoints) != 1:
        raise ValueError("expected one Nemotron .nemo checkpoint")
    # strict=False 沿用作者恢复示例；升级时须核对 missing / unexpected keys。
    model = SortformerEncLabelModel.restore_from(
        restore_path=str(checkpoints[0]),
        map_location="cuda",
        strict=False,
    )
    model.eval()
    # 作者的离线 cache / FIFO / chunk 配方，单位是模型帧而非毫秒。
    # 上限是全文件 8 个身份；分块计算不会增加身份数，也不提供实时接口。
    model.sortformer_modules.spkcache_len = 264
    model.sortformer_modules.fifo_len = 40
    model.sortformer_modules.chunk_len = 340
    model.sortformer_modules.chunk_right_context = 40
    model.sortformer_modules.spkcache_update_period = 300
    model._check_streaming_parameters()

    service = FastAPI(docs_url=None, redoc_url=None)
    lock = threading.Lock()

    @service.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @service.post("/diarize")
    def infer(request: InferenceRequest) -> InferenceResult:
        if request.audio is None:
            raise HTTPException(422, "audio is required")
        audio_path = Path(request.audio).resolve()
        if not audio_path.is_relative_to(Path("/data/asr").resolve()) or not audio_path.is_file():
            raise HTTPException(422, "audio must be a file inside /data/asr")
        with lock:
            # NeMo's file-path loader segfaults in Lhotse 2.0.0a6. The server already
            # normalizes every request to mono 16 kHz PCM, so bypass that loader.
            audio, rate = sf.read(audio_path, dtype="float32")
            if rate != 16000 or audio.ndim != 1:
                raise ValueError("diarizer expects mono 16 kHz PCM")
            # Each diarize call owns one array and initializes its own streaming cache.
            result = model.diarize(audio=[audio], sample_rate=rate, batch_size=1, num_workers=0)[0]
            spans = []
            for segment in result:
                start, end, speaker = segment.split()
                spans.append(
                    Span(
                        start_ms=round(float(start) * 1000),
                        end_ms=round(float(end) * 1000),
                        speaker=speaker,
                    )
                )
            return InferenceResult(spans=spans, raw=result)

    return service
