import asyncio
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from pydantic import JsonValue

from protocol import InferenceRequest, InferenceResult
from scheduler.config import Config, Instance
from scheduler.tracing import Trace


class Models:
    def __init__(self, config: Config, http: httpx2.AsyncClient | None = None) -> None:
        self.config = config
        self.http = http or httpx2.AsyncClient(trust_env=False)
        self.cpu = asyncio.Semaphore(config.cpu_requests)
        self.available = asyncio.Condition()
        self.instances = config.instances
        self.loads = [0] * len(self.instances)

    @asynccontextmanager
    async def acquire(self, model: str) -> AsyncIterator[Instance]:
        indices = [i for i, instance in enumerate(self.instances) if instance.model == model]
        if not indices:
            raise ValueError(f"model is not deployed: {model}")
        async with self.available:
            await self.available.wait_for(
                lambda: any(self.loads[i] < self.instances[i].capacity for i in indices)
            )
            index = min(indices, key=lambda i: self.loads[i] / self.instances[i].capacity)
            self.loads[index] += 1
        try:
            yield self.instances[index]
        finally:
            async with self.available:
                self.loads[index] -= 1
                self.available.notify_all()


class Inference:
    def __init__(self, models: Models, work: Path, trace: Trace, recipe: str) -> None:
        self.models, self.work, self.trace, self.recipe = models, work, trace, recipe
        self.records: list[JsonValue] = []

    async def call(
        self, model: str, request: InferenceRequest, *, step: str, channel: str | None = None
    ) -> InferenceResult:
        started = time.monotonic()
        operation = {
            "firered-punc": "punctuate",
            "firered-vad": "vad",
            "pyannote-community-1": "diarize",
            "nemotron-diarization": "diarize",
            "qwen3-aligner": "align",
        }.get(model, "transcribe")
        data = request.model_dump(mode="json", exclude={"audio"})
        async with self.models.acquire(model) as instance:
            audio = (
                await asyncio.to_thread(Path(request.audio).read_bytes) if request.audio else None
            )
            infer_started = time.monotonic()
            response = await self.models.http.post(
                instance.url + "/" + operation,
                data={"options": json.dumps(data)},
                files={"file": ("audio.wav", audio, "audio/wav")} if audio is not None else None,
                timeout=3600,
            )
            response.raise_for_status()
            result = InferenceResult.model_validate_json(response.content)
        self.records.append(
            {"model": model, "request": data, "result": result.model_dump(mode="json")}
        )
        self.trace.add(
            kind="model",
            name=step,
            recipe=self.recipe,
            channel=channel,
            model=model,
            started=started,
            model_queue_ms=round((infer_started - started) * 1000),
            inference_ms=round((time.monotonic() - infer_started) * 1000),
            input_summary={"audio": Path(request.audio).name if request.audio else None},
            output_summary={"text_chars": len(result.text), "span_count": len(result.spans)},
        )
        return result
