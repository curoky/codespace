import asyncio
import tempfile
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from fastapi import FastAPI, Form, HTTPException, UploadFile
from pydantic import JsonValue

from scheduler.audio import inspect
from scheduler.config import Config, read_config
from scheduler.inference import Inference, Models
from scheduler.options import Options
from scheduler.scenarios import RECIPES
from scheduler.tracing import Trace
from scheduler.transcript import Transcript


def create_app(
    config: Config, models: Models | None = None, *, work_dir: Path = Path("/data/asr")
) -> FastAPI:
    runtime = models or Models(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        work_dir.mkdir(parents=True, exist_ok=True)
        yield
        await runtime.http.aclose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/transcribe")
    async def submit(file: UploadFile, options: Annotated[str, Form()]) -> dict[str, JsonValue]:
        parameters = Options.model_validate_json(options)
        registered = RECIPES[parameters.scenario]
        selected = parameters.recipes or list(registered)
        if len(set(selected)) != len(selected) or any(name not in registered for name in selected):
            raise HTTPException(422, "unknown or duplicate recipe")
        trace = Trace()
        records: dict[str, JsonValue] = {}
        with tempfile.TemporaryDirectory(prefix="request-", dir=work_dir) as temporary:
            work = Path(temporary)
            source = work / "audio.wav"
            started = time.monotonic()
            with source.open("wb") as target:
                while chunk := await file.read(1024 * 1024):
                    await asyncio.to_thread(target.write, chunk)
            duration, channels = await asyncio.to_thread(inspect, source)
            expected = 2 if parameters.scenario == "conversation_tracks" else 1
            if channels != expected or duration <= 0:
                raise HTTPException(422, f"scenario expects {expected} channels with audio")
            trace.add(
                kind="phase",
                name="upload",
                started=started,
                input_summary={"filename": file.filename or "audio.wav"},
            )

            async def execute(name: str) -> Transcript:
                directory = work / name
                directory.mkdir()
                inference = Inference(runtime, directory, trace, f"{parameters.scenario}/{name}")
                started = time.monotonic()
                result = await registered[name](inference, source, duration, parameters)
                records[name] = inference.records
                trace.add(
                    kind="phase",
                    name=name,
                    recipe=result.recipe,
                    started=started,
                    output_summary={"segments": len(result.segments)},
                )
                return result

            async with asyncio.TaskGroup() as tasks:
                pending = [tasks.create_task(execute(name)) for name in selected]
            results = [task.result() for task in pending]
        await file.close()
        return {
            "results": [result.model_dump(mode="json") for result in results],
            "evidence": {
                "filename": file.filename,
                "options": parameters.model_dump(mode="json"),
                "recipes": records,
            },
            "trace": trace.document(),
        }

    return app


def main(
    config: Path = Path("/opt/asr/scheduler/scheduler.yaml"),
    host: str = "0.0.0.0",  # noqa: S104 - published scheduler API
    port: int = 8080,
) -> None:
    uvicorn.run(create_app(read_config(config)), host=host, port=port, workers=1)


if __name__ == "__main__":
    typer.run(main)
