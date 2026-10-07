import asyncio
import contextlib
import importlib.util
import sys
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import httpx

from models.catalog import MODELS, ModelSpec
from ops.processes import GPU, service, visible_gpus
from protocol import InferenceRequest, InferenceResult
from server.config import Config


@dataclass
class Instance:
    spec: ModelSpec
    directory: Path
    url: str
    client: Callable[[httpx.AsyncClient, InferenceRequest], Awaitable[InferenceResult]]
    devices: list[str] = field(default_factory=list)
    running: bool = False
    active: bool = False
    last_used: float = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Scheduler:
    def __init__(
        self,
        config: Config,
        *,
        runtime_dir: Path = Path("/run/asr"),
        control: Callable[[str, str], Awaitable[None]] = service,
        inventory: Callable[[str | list[str]], Awaitable[list[GPU]]] = visible_gpus,
    ) -> None:
        self.config = config
        self.runtime_dir = runtime_dir
        self.control = control
        self.inventory = inventory
        self.instances: dict[str, Instance] = {}
        self.condition = asyncio.Condition()
        self.waiters: deque[str] = deque()
        self.http = httpx.AsyncClient(timeout=10, trust_env=False)
        self.cpu = asyncio.Semaphore(config.cpu_requests)
        for spec in MODELS:
            directory = Path(__file__).resolve().parents[1] / "models" / spec.id
            module_spec = importlib.util.spec_from_file_location(
                "asr_client_" + spec.id.replace("-", "_").replace(".", "_"),
                directory / "client.py",
            )
            if module_spec is None or module_spec.loader is None:
                raise ValueError(f"{spec.id}: client.py cannot be loaded")
            module = importlib.util.module_from_spec(module_spec)
            sys.modules[module_spec.name] = module
            module_spec.loader.exec_module(module)
            client = cast(
                Callable[[httpx.AsyncClient, InferenceRequest], Awaitable[InferenceResult]],
                module.infer,
            )
            self.instances[spec.id] = Instance(spec, directory, module.URL, client)

    async def initialize(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        for model in self.instances:
            await self.control("stop", model)

    async def close(self) -> None:
        for instance in self.instances.values():
            if instance.running:
                await self.control("stop", instance.spec.id)
        await self.http.aclose()

    async def _stop(self, instance: Instance) -> None:
        await self.control("stop", instance.spec.id)
        instance.running = False
        instance.devices.clear()

    async def _start(self, instance: Instance) -> None:
        spec = instance.spec
        if spec.resources.gpus:
            directory = self.runtime_dir / spec.id
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "CUDA_VISIBLE_DEVICES").write_text(",".join(instance.devices))
        instance.running = True
        await self.control("start", spec.id)
        deadline = time.monotonic() + spec.resources.startup_seconds
        while time.monotonic() < deadline:
            try:
                response = await self.http.get(f"{instance.url}/health")
                if response.is_success:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(1)
        raise TimeoutError(f"{spec.id}: readiness timeout")

    async def acquire(self, model: str) -> Instance:
        instance = self.instances[model]
        await instance.lock.acquire()
        try:
            if not instance.spec.resources.gpus:
                if not instance.running:
                    await self._start(instance)
                instance.active = True
                return instance
            async with self.condition:
                self.waiters.append(model)
                deadline = time.monotonic() + self.config.resources.wait_seconds
                try:
                    while True:
                        if self.waiters[0] == model:
                            if instance.running:
                                instance.active = True
                                break
                            devices = await self.inventory(self.config.resources.gpu_pool)
                            required = instance.spec.resources.gpus
                            if required > len(devices):
                                raise RuntimeError(f"{model}: requires {required} visible GPUs")
                            reserved = {d for i in self.instances.values() for d in i.devices}
                            available = [
                                d
                                for d in devices
                                if d.id not in reserved
                                and d.free_mib >= instance.spec.resources.memory_gib * 1024
                                and d.total_mib - d.free_mib <= 512
                            ]
                            if len(available) >= required:
                                instance.devices = [d.id for d in available[:required]]
                                instance.active = True
                                break
                            idle = [
                                i
                                for i in self.instances.values()
                                if i.running and not i.active and i.devices
                            ]
                            if idle:
                                await self._stop(min(idle, key=lambda i: i.last_used))
                                continue
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError(f"{model}: resource wait timeout")
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(self.condition.wait(), min(remaining, 1))
                finally:
                    self.waiters.remove(model)
                    self.condition.notify_all()
            if not instance.running:
                await self._start(instance)
            return instance
        except BaseException:
            await self.release(instance, failed=True)
            raise

    async def release(self, instance: Instance, *, failed: bool = False) -> None:
        async with self.condition:
            instance.active = False
            instance.last_used = time.monotonic()
            try:
                if failed and instance.running:
                    await self._stop(instance)
            finally:
                if instance.lock.locked():
                    instance.lock.release()
                self.condition.notify_all()
