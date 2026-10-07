import asyncio
from pathlib import Path

from pydantic import JsonValue

from ops.scheduler import Scheduler
from protocol import InferenceRequest, InferenceResult, Record
from server.storage import atomic_text, digest, file_hash


class Inference:
    def __init__(self, scheduler: Scheduler, work: Path) -> None:
        self.scheduler = scheduler
        self.work = work
        self.locks: dict[str, asyncio.Lock] = {}
        self.records: dict[str, JsonValue] = {}

    async def call(self, model: str, request: InferenceRequest) -> InferenceResult:
        instance = self.scheduler.instances[model]
        effective = request.model_copy(deep=True)
        if not instance.spec.hotwords:
            effective.hotwords = []
        if not instance.spec.num_speakers:
            effective.num_speakers = None
        identity = effective.model_dump(mode="json")
        if effective.audio:
            identity["audio"] = await asyncio.to_thread(file_hash, Path(effective.audio))
        key = digest({"request": identity, "model": instance.fingerprint})
        cache = self.work / "responses" / f"{key}.json"
        async with self.locks.setdefault(key, asyncio.Lock()):
            if cache.is_file():
                record = CachedResponse.model_validate_json(cache.read_text())
                self.records[key] = record.model_dump(mode="json")
                return record.result
            instance = await self.scheduler.acquire(model)
            failed = True
            try:
                if instance.spec.resources.gpus:
                    result = await instance.client(self.scheduler.http, effective)
                else:
                    async with self.scheduler.cpu:
                        result = await instance.client(self.scheduler.http, effective)
                record = CachedResponse(
                    model=model,
                    request=identity,
                    result=result,
                    fingerprint=instance.fingerprint,
                    audio_file=Path(effective.audio).name if effective.audio else None,
                )
                await asyncio.to_thread(atomic_text, cache, record.model_dump_json())
                self.records[key] = record.model_dump(mode="json")
                failed = False
                return result
            finally:
                await self.scheduler.release(instance, failed=failed)


class CachedResponse(Record):
    model: str
    fingerprint: str
    request: dict[str, JsonValue]
    result: InferenceResult
    audio_file: str | None = None
