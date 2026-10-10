import asyncio
import contextlib
import importlib.util
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import httpx2

from models.catalog import MODELS, ModelSpec
from ops.processes import GPU, GPUUtilization, gpu_utilization, service, visible_gpus
from protocol import InferenceRequest, InferenceResult
from server.config import Config, ModelInstanceConfig


@dataclass
class Instance:
    id: str
    model: str
    spec: ModelSpec
    url: str
    placement: list[int]
    client: Callable[[httpx2.AsyncClient, str, InferenceRequest], Awaitable[InferenceResult]]
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
        control: Callable[[str, list[str]], Awaitable[None]] = service,
        inventory: Callable[[], Awaitable[list[GPU]]] = visible_gpus,
        utilization: Callable[[list[str]], Awaitable[list[GPUUtilization]]] = gpu_utilization,
    ) -> None:
        self.config = config
        self.runtime_dir = runtime_dir
        self.control = control
        self.inventory = inventory
        self.utilization = utilization
        self.instances: dict[str, Instance] = {}
        self.pools: dict[str, list[Instance]] = {}
        self.conditions: dict[str, asyncio.Condition] = {}
        self.http = httpx2.AsyncClient(timeout=10, trust_env=False)
        self.cpu = asyncio.Semaphore(config.cpu_requests)
        specs = {spec.id: spec for spec in MODELS}
        clients: dict[
            str,
            Callable[[httpx2.AsyncClient, str, InferenceRequest], Awaitable[InferenceResult]],
        ] = {}
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
                Callable[[httpx2.AsyncClient, str, InferenceRequest], Awaitable[InferenceResult]],
                module.infer,
            )
            clients[spec.id] = client
        for configured in config.resources.instances:
            try:
                spec = specs[configured.model]
            except KeyError as exc:
                raise ValueError(f"{configured.id}: unknown model {configured.model}") from exc
            if len(configured.placement) != spec.gpus:
                raise ValueError(
                    f"{configured.id}: expected {spec.gpus} GPUs, got {len(configured.placement)}"
                )
            if len(set(configured.placement)) != len(configured.placement):
                raise ValueError(f"{configured.id}: GPU placement must be unique")
            instance = self._instance(configured, spec, clients[spec.id])
            self.instances[instance.id] = instance
            self.pools.setdefault(instance.model, []).append(instance)
        missing = set(specs) - set(self.pools)
        if missing:
            raise ValueError(f"models without instances: {', '.join(sorted(missing))}")
        self.conditions = {model: asyncio.Condition() for model in self.pools}

    @property
    def gpu_ids(self) -> list[str]:
        devices = {
            device_id: int(index)
            for instance in self.instances.values()
            for device_id, index in zip(instance.devices, instance.gpu_indices, strict=True)
        }
        return [device_id for device_id, _ in sorted(devices.items(), key=lambda item: item[1])]

    @staticmethod
    def _instance(
        configured: ModelInstanceConfig,
        spec: ModelSpec,
        client: Callable[[httpx2.AsyncClient, str, InferenceRequest], Awaitable[InferenceResult]],
    ) -> Instance:
        return Instance(
            configured.id,
            configured.model,
            spec,
            f"http://127.0.0.1:{configured.port}",
            list(configured.placement),
            client,
        )

    def spec(self, model: str) -> ModelSpec:
        return self.pools[model][0].spec

    async def initialize(self) -> None:
        """把逻辑 placement 固定到可见 GPU，并在 HTTP ready 前启动全部模型。"""
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        instance_ids = list(self.instances)
        await self.control("stop", instance_ids)

        devices = await self.inventory()
        loads = [0.0] * len(devices)
        for instance in self.instances.values():
            if not instance.spec.gpus:
                continue
            placement = instance.placement
            try:
                assigned = [devices[index] for index in placement]
            except IndexError as exc:
                raise RuntimeError(
                    f"{instance.id}: placement requires {max(placement) + 1} visible GPUs"
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
                self._write_runtime(instance)
                instance.running = True
            await self.control("start", instance_ids)
            await asyncio.gather(
                *(self._wait_ready(instance) for instance in self.instances.values())
            )
        except BaseException:
            with contextlib.suppress(Exception):
                await self.control("stop", instance_ids)
            for instance in self.instances.values():
                instance.running = False
            raise

    async def close(self) -> None:
        await self.http.aclose()

    def _write_runtime(self, instance: Instance) -> None:
        directory = self.runtime_dir / instance.id
        directory.mkdir(parents=True, exist_ok=True)
        if instance.spec.gpus:
            (directory / "CUDA_VISIBLE_DEVICES").write_text(",".join(instance.devices))
        (directory / "PORT").write_text(str(httpx2.URL(instance.url).port))

    async def _wait_ready(self, instance: Instance) -> None:
        deadline = time.monotonic() + instance.spec.startup_seconds
        while time.monotonic() < deadline:
            try:
                response = await self.http.get(f"{instance.url}/health")
                if response.is_success:
                    return
            except httpx2.TransportError:
                pass
            await asyncio.sleep(1)
        raise TimeoutError(f"{instance.id}: readiness timeout")

    async def acquire(
        self,
        model: str,
        metrics: AcquireMetrics | None = None,
        *,
        instance_id: str | None = None,
    ) -> Instance:
        metrics = metrics or AcquireMetrics()
        started = time.monotonic()
        pool = self.pools[model]
        if instance_id is not None:
            pool = [instance for instance in pool if instance.id == instance_id]
            if not pool:
                raise ValueError(f"{instance_id}: not an instance of {model}")
        condition = self.conditions[model]
        async with condition:
            while True:
                instance = next(
                    (candidate for candidate in pool if not candidate.lock.locked()), None
                )
                if instance is not None:
                    await instance.lock.acquire()
                    break
                await condition.wait()
        metrics.model_queue_seconds = time.monotonic() - started
        return instance

    async def release(self, instance: Instance) -> None:
        if instance.lock.locked():
            instance.lock.release()
            async with self.conditions[instance.model]:
                self.conditions[instance.model].notify_all()
