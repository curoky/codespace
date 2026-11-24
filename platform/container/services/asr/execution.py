"""Request-owned concurrency and cancellation-safe filesystem work."""

import asyncio
from collections.abc import Callable, Coroutine


async def collect[T](*coroutines: Coroutine[None, None, T]) -> list[T]:
    async with asyncio.TaskGroup() as tasks:
        pending = [tasks.create_task(coroutine) for coroutine in coroutines]
    return [task.result() for task in pending]


async def blocking[**P, T](function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Task cancellation cannot stop a thread that still uses request files.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not task.cancelled():
            task.exception()
        raise
