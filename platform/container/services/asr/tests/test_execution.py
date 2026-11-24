import asyncio
from threading import Event

import pytest

from execution import blocking, collect


def test_collect_preserves_order_and_cancels_siblings_on_failure() -> None:
    async def run() -> None:
        entered = asyncio.Event()
        finished = asyncio.Event()

        async def waiting() -> int:
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                finished.set()
            return 1

        async def failing() -> int:
            await entered.wait()
            raise ValueError("model failed")

        with pytest.raises(ExceptionGroup):
            await collect(waiting(), failing())
        assert finished.is_set()

        async def value(number: int) -> int:
            await asyncio.sleep(0)
            return number

        assert await collect(value(2), value(1)) == [2, 1]

    asyncio.run(run())


@pytest.mark.parametrize("failure", [False, True])
def test_blocking_waits_for_threads_before_propagating_repeated_cancellation(failure: bool) -> None:
    async def run() -> None:
        entered = Event()
        release = Event()
        finished = Event()

        def work() -> None:
            entered.set()
            try:
                assert release.wait(2)
                if failure:
                    raise ValueError("thread failed")
            finally:
                finished.set()

        task = asyncio.create_task(blocking(work))
        try:
            while not entered.is_set():
                await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    asyncio.run(run())


def test_blocking_preserves_results_and_exceptions() -> None:
    async def run() -> None:
        assert await blocking(pow, 2, 3) == 8

        def fail() -> None:
            raise ValueError("failed")

        with pytest.raises(ValueError, match="failed"):
            await blocking(fail)

    asyncio.run(run())
