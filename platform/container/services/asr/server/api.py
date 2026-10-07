import asyncio
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from fastapi import FastAPI, Form, HTTPException, Response, UploadFile
from pydantic import ValidationError

from ops.scheduler import Scheduler
from server.artifacts import bundle
from server.config import Config, read_config
from server.recipes import Options
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
    async def submit(file: UploadFile, options: Annotated[str, Form()] = "{}") -> Response:
        try:
            parameters = Options.model_validate_json(options)
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            with tempfile.TemporaryDirectory(prefix="request-", dir=work_dir) as temporary:
                work = Path(temporary)
                source = work / "original"
                with source.open("wb") as target:
                    while chunk := await file.read(1024 * 1024):
                        await asyncio.to_thread(target.write, chunk)
                if not source.stat().st_size:
                    raise HTTPException(422, "empty file")
                results, evidence = await transcribe(source, work, config, runtime, parameters)
                archive = await asyncio.to_thread(
                    bundle,
                    results,
                    {
                        "filename": file.filename or "recording",
                        "options": parameters.model_dump(mode="json"),
                        "config": config.model_dump(mode="json"),
                        "channels": evidence,
                    },
                )
                return Response(
                    archive,
                    media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="transcripts.zip"'},
                )
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
