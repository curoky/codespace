import asyncio
import os
import signal

from pydantic import Field

from protocol import Record


async def command(*args: str, timeout: float = 60) -> str:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
        raise
    if process.returncode:
        raise RuntimeError(f"{args[0]} exited {process.returncode}: {stderr.decode()[-2000:]}")
    return stdout.decode()


class GPU(Record):
    id: str
    index: str
    total_mib: int = Field(ge=0)
    free_mib: int = Field(ge=0)


async def visible_gpus() -> list[GPU]:
    try:
        result = await command(
            "nvidia-smi",
            "--query-gpu=uuid,index,memory.total,memory.free",
            "--format=csv,noheader,nounits",
        )
    except FileNotFoundError:
        return []
    devices = []
    requested = os.environ.get("CUDA_VISIBLE_DEVICES")
    allowed = requested.split(",") if requested is not None else None
    for row in result.strip().splitlines():
        uuid, index, total, free = [field.strip() for field in row.split(",")]
        if allowed is not None and uuid not in allowed and index not in allowed:
            continue
        devices.append(GPU(id=uuid, index=index, total_mib=int(total), free_mib=int(free)))
    if allowed is not None:
        order = {device: position for position, device in enumerate(allowed)}
        devices.sort(key=lambda device: order.get(device.id, order.get(device.index, len(order))))
    return devices


async def service(action: str, model: str) -> None:
    await command("sudo", "-n", "/usr/local/bin/asr-model-service", action, model, timeout=7200)
