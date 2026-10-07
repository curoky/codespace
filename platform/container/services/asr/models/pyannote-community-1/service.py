import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException

from protocol import InferenceRequest, InferenceResult, Span


def app() -> FastAPI:
    import soundfile as sf
    import torch
    from pyannote.audio import Pipeline

    weights = Path(__file__).resolve().parent / "weights"
    model = Pipeline.from_pretrained(str(weights))
    model.to(torch.device("cuda"))

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
            # 直接传 waveform，避免引入另一套音频解码器；人数只采用用户明确输入。
            audio, rate = sf.read(request.audio, dtype="float32", always_2d=True)
            kwargs = {"num_speakers": request.num_speakers} if request.num_speakers else {}
            result = model({"waveform": torch.from_numpy(audio.T), "sample_rate": rate}, **kwargs)
            # 使用普通 diarization 保留重叠，exclusive 输出会抹掉插话。
            # 标签仅在本文件内有效，不能逐短窗重新聚类或跨文件识别人名。
            spans = [
                Span(
                    start_ms=round(turn.start * 1000),
                    end_ms=round(turn.end * 1000),
                    speaker=str(speaker),
                )
                for turn, speaker in result.speaker_diarization
            ]
            return InferenceResult(spans=spans, raw=[span.model_dump() for span in spans])

    return service
