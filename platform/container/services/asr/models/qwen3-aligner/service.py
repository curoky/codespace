import json
import re
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException

from protocol import InferenceRequest, InferenceResult, Token


def app() -> FastAPI:
    import soundfile as sf
    from vllm import LLM

    weights = Path(__file__).resolve().parent / "weights"
    config = json.loads((weights / "config.json").read_text())
    # 时间 token 和步长必须从配套 checkpoint 读取，不能当作置信度。
    timestamp_id = config["timestamp_token_id"]
    timestamp_ms = config["timestamp_segment_time"]
    # 通用 pooling HTTP 缺少解码所需的 prompt_token_ids，故在本目录直接用 LLM.encode。
    # eager 避免 pooling CUDA Graph 的额外约束；8192 为文本与音频留上下文预算。
    # 0.10 约占 8 GiB；pooling 不需要生成式 KV cache，增大比例只会挤占同卡常驻模型。
    model = LLM(
        model=str(weights),
        runner="pooling",  # timestamp token 分类，不是文本 generate
        dtype="bfloat16",
        enforce_eager=True,
        max_model_len=8192,
        tensor_parallel_size=1,
        gpu_memory_utilization=0.10,
        hf_overrides={"architectures": ["Qwen3ASRForcedAlignerForTokenClassification"]},
    )

    service = FastAPI(docs_url=None, redoc_url=None)
    lock = threading.Lock()

    @service.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @service.post("/align")
    def infer(request: InferenceRequest) -> InferenceResult:
        if request.audio is None:
            raise HTTPException(422, "audio is required")
        audio_path = Path(request.audio).resolve()
        if not audio_path.is_relative_to(Path("/data/asr").resolve()) or not audio_path.is_file():
            raise HTTPException(422, "audio must be a file inside /data/asr")
        with lock:
            # Chinese characters and whitespace-delimited Latin words match the author's tokenizer.
            words = re.findall(r"[\u3400-\u9fff]|[^\W_\u3400-\u9fff]+", request.text)
            if not words:
                return InferenceResult(text=request.text)
            prompt = "<|audio_start|><|audio_pad|><|audio_end|>" + "".join(
                word + "<timestamp><timestamp>" for word in words
            )
            audio, rate = sf.read(request.audio, dtype="float32")
            if rate != 16000 or audio.ndim != 1:
                raise ValueError("aligner expects mono 16 kHz PCM")
            result = model.encode(
                [{"prompt": prompt, "multi_modal_data": {"audio": audio}}],
                pooling_task="token_classify",
            )[0]
            predictions = result.outputs.data.argmax(dim=-1).cpu().tolist()
            times = [
                predictions[i] * timestamp_ms
                for i, token in enumerate(result.prompt_token_ids)
                if token == timestamp_id
            ]
            if len(times) != len(words) * 2:
                raise ValueError("aligner returned incomplete timestamp tokens")
            # 对齐不证明正文正确；越界或缺失时间保持 null，不均分填补。
            tokens = []
            duration = len(audio) / 16
            for index, word in enumerate(words):
                start, end = times[2 * index : 2 * index + 2]
                valid = 0 <= start <= end <= duration
                tokens.append(
                    Token(
                        text=word,
                        start_ms=int(start) if valid else None,
                        end_ms=int(end) if valid else None,
                    )
                )
            return InferenceResult(
                text=request.text,
                tokens=tokens,
                warnings=["alignment_failed"] if any(t.start_ms is None for t in tokens) else [],
            )

    return service
