import asyncio
import time
from pathlib import Path

from pydantic import JsonValue

from ops.scheduler import AcquireMetrics, Instance, Scheduler
from protocol import InferenceRequest, InferenceResult
from server.tracing import Trace


class Inference:
    def __init__(
        self, scheduler: Scheduler, work: Path, trace: Trace | None = None, channel: str = "mono"
    ) -> None:
        self.scheduler = scheduler
        self.work = work
        self.trace = trace or Trace()
        self.channel = channel
        self.responses: dict[tuple[str, str], InferenceResult] = {}
        self.response_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self.records: list[JsonValue] = []

    @staticmethod
    def input_summary(request: InferenceRequest) -> dict[str, JsonValue]:
        summary: dict[str, JsonValue] = {
            "text_chars": len(request.text),
            "hotword_count": len(request.hotwords),
            "num_speakers": request.num_speakers,
        }
        if request.audio:
            audio = Path(request.audio)
            summary.update({"audio": audio.name, "audio_bytes": audio.stat().st_size})
        return summary

    @staticmethod
    def output_summary(result: InferenceResult) -> dict[str, JsonValue]:
        return {
            "text_chars": len(result.text),
            "span_count": len(result.spans),
            "token_count": len(result.tokens),
            "warning_count": len(result.warnings),
            "last_end_ms": max((span.end_ms for span in result.spans), default=None),
        }

    async def call(
        self,
        model: str,
        request: InferenceRequest,
        *,
        step: str = "model",
        instance_id: str | None = None,
    ) -> InferenceResult:
        """在本请求内合并相同调用，再从逻辑模型的实例池取得副本。"""
        started = self.trace.begin()
        effective = request.model_copy(deep=True)
        spec = self.scheduler.spec(model)
        if not spec.hotwords:
            effective.hotwords = []
        if not spec.num_speakers:
            effective.num_speakers = None
        # 切片在本次请求内不可变；只复用相同模型、切片和参数，不做跨请求缓存。
        key = (model, effective.model_dump_json())
        if key in self.responses:
            result = self.responses[key].model_copy(deep=True)
            self.trace.add(
                kind="model",
                name=step,
                channel=self.channel,
                model=model,
                started=started,
                status="completed",
                cache_hit=True,
                input_summary=self.input_summary(effective),
                output_summary=self.output_summary(result),
            )
            return result
        metrics = AcquireMetrics()
        acquired: Instance | None = None
        gpu_ids: list[str] = []
        gpu_indices: list[str] = []
        cpu_queue_seconds = 0.0
        inference_seconds = 0.0
        output: dict[str, JsonValue] = {}
        error: str | None = None
        cache_hit = False
        failed = True
        try:
            async with self.response_locks.setdefault(key, asyncio.Lock()):
                # 相同请求在这里 single-flight，不会因副本数增加而重复推理。
                if key in self.responses:
                    result = self.responses[key].model_copy(deep=True)
                    output = self.output_summary(result)
                    cache_hit = True
                    failed = False
                    return result
                acquired = await self.scheduler.acquire(model, metrics, instance_id=instance_id)
                gpu_ids = list(acquired.devices)
                gpu_indices = list(acquired.gpu_indices)
                if acquired.spec.gpus:
                    inference_started = time.monotonic()
                    result = await acquired.client(self.scheduler.http, acquired.url, effective)
                    inference_seconds = time.monotonic() - inference_started
                else:
                    cpu_started = time.monotonic()
                    async with self.scheduler.cpu:
                        cpu_queue_seconds = time.monotonic() - cpu_started
                        inference_started = time.monotonic()
                        result = await acquired.client(self.scheduler.http, acquired.url, effective)
                        inference_seconds = time.monotonic() - inference_started
                self.responses[key] = result.model_copy(deep=True)
                output = self.output_summary(result)
                parameters = effective.model_dump(mode="json")
                if effective.audio:
                    parameters["audio"] = Path(effective.audio).name
                self.records.append(
                    {
                        "model": model,
                        "request": parameters,
                        "result": result.model_dump(mode="json"),
                    }
                )
                failed = False
                return result
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            if acquired is not None:
                await self.scheduler.release(acquired)
            self.trace.add(
                kind="model",
                name=step,
                channel=self.channel,
                model=model,
                started=started,
                status="failed" if failed else "completed",
                cache_hit=cache_hit,
                gpu_ids=gpu_ids,
                gpu_indices=gpu_indices,
                model_queue_seconds=metrics.model_queue_seconds,
                cpu_queue_seconds=cpu_queue_seconds,
                inference_seconds=inference_seconds,
                input_summary=self.input_summary(effective),
                output_summary=output,
                error=error,
            )
