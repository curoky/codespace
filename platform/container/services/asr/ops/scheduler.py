import asyncio
import contextlib
import importlib.util
import sys
import time
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
    url: str
    client: Callable[[httpx.AsyncClient, InferenceRequest], Awaitable[InferenceResult]]
    devices: list[str] = field(default_factory=list)
    gpu_indices: list[str] = field(default_factory=list)
    running: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class AcquireMetrics:
    model_queue_seconds: float = 0


class Scheduler:
    def __init__(
        self,
        config: Config,
        *,
        runtime_dir: Path = Path("/run/asr"),
        control: Callable[[str, str], Awaitable[None]] = service,
        inventory: Callable[[], Awaitable[list[GPU]]] = visible_gpus,
    ) -> None:
        self.config = config
        self.runtime_dir = runtime_dir
        self.control = control
        self.inventory = inventory
        self.instances: dict[str, Instance] = {}
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
            self.instances[spec.id] = Instance(spec, module.URL, client)

    async def initialize(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        for model in self.instances:
            await self.control("stop", model)

        devices = await self.inventory()
        loads = [0.0] * len(devices)
        for instance in self.instances.values():
            if not instance.spec.gpus:
                continue
            placement = self.config.resources.placement[instance.spec.id]
            try:
                assigned = [devices[index] for index in placement]
            except IndexError as exc:
                raise RuntimeError(
                    f"{instance.spec.id}: placement requires {max(placement) + 1} visible GPUs"
                ) from exc
            instance.devices = [device.id for device in assigned]
            instance.gpu_indices = [device.index for device in assigned]
            for index in placement:
                loads[index] += instance.spec.memory_gib

        for index, load in enumerate(loads):
            if not load:
                continue
            device = devices[index]
            if device.free_mib < load * 1024 or device.total_mib - device.free_mib > 512:
                raise RuntimeError(
                    f"GPU {device.index}: static placement needs {load:g} GiB on an idle device"
                )

        try:
            for instance in self.instances.values():
                await self._start(instance)
        except BaseException:
            for instance in self.instances.values():
                if instance.running:
                    with contextlib.suppress(Exception):
                        await self._stop(instance)
            raise

    async def close(self) -> None:
        await self.http.aclose()

    async def _stop(self, instance: Instance) -> None:
        await self.control("stop", instance.spec.id)
        instance.running = False

    async def _start(self, instance: Instance) -> None:
        if instance.spec.gpus:
            directory = self.runtime_dir / instance.spec.id
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "CUDA_VISIBLE_DEVICES").write_text(",".join(instance.devices))
        instance.running = True
        await self.control("start", instance.spec.id)
        deadline = time.monotonic() + instance.spec.startup_seconds
        while time.monotonic() < deadline:
            try:
                response = await self.http.get(f"{instance.url}/health")
                if response.is_success:
                    return
            except httpx.TransportError:
                pass
            await asyncio.sleep(1)
        raise TimeoutError(f"{instance.spec.id}: readiness timeout")

    async def acquire(self, model: str, metrics: AcquireMetrics | None = None) -> Instance:
        metrics = metrics or AcquireMetrics()
        instance = self.instances[model]
        started = time.monotonic()
        await instance.lock.acquire()
        metrics.model_queue_seconds = time.monotonic() - started
        return instance

    @staticmethod
    async def release(instance: Instance) -> None:
        if instance.lock.locked():
            instance.lock.release()
