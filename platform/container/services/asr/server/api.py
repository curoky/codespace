import asyncio
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

import typer
import uvicorn
from fastapi import FastAPI, Form, HTTPException, UploadFile
from pydantic import JsonValue, ValidationError

from ops.scheduler import Scheduler
from server.config import Config, read_config
from server.recipes import Options
from server.tracing import Trace
from server.transcribe import transcribe


def create_app(
    config: Config,
    scheduler: Scheduler | None = None,
    *,
    work_dir: Path = Path("/data/asr"),
) -> FastAPI:
    runtime = scheduler or Scheduler(config)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        work_dir.mkdir(parents=True, exist_ok=True)
        await runtime.initialize()
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @app.post("/transcribe")
    async def submit(
        file: UploadFile, options: Annotated[str, Form()] = "{}"
    ) -> dict[str, JsonValue]:
        trace = Trace()
        try:
            parameters = Options.model_validate_json(options)
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            async with trace.capture_gpu_utilization(runtime.gpu_ids, runtime.utilization):
                with tempfile.TemporaryDirectory(prefix="request-", dir=work_dir) as temporary:
                    work = Path(temporary)
                    source = work / "original"
                    started = trace.begin()
                    try:
                        with source.open("wb") as target:
                            while chunk := await file.read(1024 * 1024):
                                await asyncio.to_thread(target.write, chunk)
                    except Exception as exc:
                        trace.add(
                            kind="phase",
                            name="upload",
                            started=started,
                            status="failed",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                        raise
                    if not source.stat().st_size:
                        raise HTTPException(422, "empty file")
                    trace.add(
                        kind="phase",
                        name="upload",
                        started=started,
                        status="completed",
                        input_summary={"filename": file.filename or "recording"},
                        output_summary={"bytes": source.stat().st_size},
                    )
                    results, evidence = await transcribe(
                        source, work, config, runtime, parameters, trace
                    )
                    status: Literal["completed", "partial"] = (
                        "completed"
                        if all(result.status == "completed" for result in results)
                        else "partial"
                    )
                    response: dict[str, JsonValue] = {
                        "results": [result.model_dump(mode="json") for result in results],
                        "evidence": {
                            "filename": file.filename or "recording",
                            "options": parameters.model_dump(mode="json"),
                            "config": config.model_dump(mode="json"),
                            "channels": evidence,
                        },
                    }
            response["trace"] = trace.document(status).model_dump(mode="json", exclude_none=True)
            return response
        finally:
            await file.close()

    return app


def main(
    config: Path = Path("/opt/asr/server/server.yaml"),
    host: str = "0.0.0.0",  # noqa: S104 - published container API
    port: int = 8080,
) -> None:
    uvicorn.run(create_app(read_config(config)), host=host, port=port, workers=1)


if __name__ == "__main__":
    typer.run(main)
