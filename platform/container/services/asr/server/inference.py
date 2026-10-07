from pathlib import Path

from pydantic import JsonValue

from ops.scheduler import Scheduler
from protocol import InferenceRequest, InferenceResult


class Inference:
    def __init__(self, scheduler: Scheduler, work: Path) -> None:
        self.scheduler = scheduler
        self.work = work
        self.responses: dict[tuple[str, str], InferenceResult] = {}
        self.records: list[JsonValue] = []

    async def call(self, model: str, request: InferenceRequest) -> InferenceResult:
        instance = self.scheduler.instances[model]
        effective = request.model_copy(deep=True)
        if not instance.spec.hotwords:
            effective.hotwords = []
        if not instance.spec.num_speakers:
            effective.num_speakers = None
        # 切片在本次请求内不可变；只复用相同模型、切片和参数，不做跨请求缓存。
        key = (model, effective.model_dump_json())
        if key in self.responses:
            return self.responses[key].model_copy(deep=True)
        instance = await self.scheduler.acquire(model)
        failed = True
        try:
            if instance.spec.resources.gpus:
                result = await instance.client(self.scheduler.http, effective)
            else:
                async with self.scheduler.cpu:
                    result = await instance.client(self.scheduler.http, effective)
            self.responses[key] = result.model_copy(deep=True)
            parameters = effective.model_dump(mode="json")
            if effective.audio:
                parameters["audio"] = Path(effective.audio).name
            self.records.append(
                {"model": model, "request": parameters, "result": result.model_dump(mode="json")}
            )
            failed = False
            return result
        finally:
            await self.scheduler.release(instance, failed=failed)
