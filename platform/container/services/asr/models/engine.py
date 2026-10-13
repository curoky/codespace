import asyncio
import os

import uvicorn
from fastapi import FastAPI


class Engine:
    def __init__(self) -> None:
        self.port = int(os.environ.get("ASR_PORT", "8000"))
        self.engine_port = self.port + 1000

    async def serve(self, app: FastAPI, command: list[str]) -> None:
        engine = await asyncio.create_subprocess_exec(*command)
        server = uvicorn.Server(
            uvicorn.Config(app, host="0.0.0.0", port=self.port, workers=1)  # noqa: S104
        )
        serving = asyncio.create_task(server.serve())
        stopped = asyncio.create_task(engine.wait())
        try:
            await asyncio.wait([serving, stopped], return_when=asyncio.FIRST_COMPLETED)
            if stopped.done():
                server.should_exit = True
                await serving
                raise RuntimeError(f"model engine exited: {engine.returncode}")
            await serving
        finally:
            if engine.returncode is None:
                engine.terminate()
                try:
                    await asyncio.wait_for(asyncio.shield(stopped), 20)
                except TimeoutError:
                    engine.kill()
            await stopped

    def __call__(self, app: FastAPI, command: list[str]) -> None:
        asyncio.run(self.serve(app, command))


run = Engine()
