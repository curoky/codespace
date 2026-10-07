import asyncio
import hashlib
import re
import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from fastapi import FastAPI, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import JsonValue, ValidationError

from ops.scheduler import Scheduler
from server.config import Config, read_config
from server.jobs import Jobs, Resolved, Status
from server.recipes import Options
from server.storage import atomic_text


def create_app(config: Config, scheduler: Scheduler | None = None) -> FastAPI:
    runtime = scheduler or Scheduler(config)
    jobs = Jobs(config, runtime)
    submission_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await runtime.initialize()
        await jobs.start()
        try:
            yield
        finally:
            await jobs.close()
            await runtime.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.jobs = jobs

    @app.get("/health")
    def health() -> dict[str, JsonValue]:
        return {"status": "ready", "deployment": jobs.deployment}

    @app.get("/models")
    def models() -> dict[str, JsonValue]:
        return {
            name: {
                "config": instance.spec.model_dump(mode="json"),
                "loaded": instance.running,
                "fingerprint": instance.fingerprint,
            }
            for name, instance in runtime.instances.items()
        }

    @app.post("/jobs", status_code=202)
    async def submit(
        file: UploadFile,
        options: Annotated[str, Form()] = "{}",
        idempotency_key: Annotated[str | None, Header()] = None,
    ) -> Status:
        try:
            parameters = Options.model_validate_json(options)
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        if idempotency_key is not None and not re.fullmatch(r"[a-f0-9]{64}", idempotency_key):
            raise HTTPException(422, "Idempotency-Key must be a SHA256 hex string")
        job = idempotency_key[:32] if idempotency_key else uuid.uuid4().hex
        staging = jobs.root / f".upload-{uuid.uuid4().hex}"
        (staging / "input").mkdir(parents=True)
        checksum = hashlib.sha256()
        size = 0
        try:
            with (staging / "input" / "original").open("wb") as target:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > config.max_upload_bytes:
                        raise HTTPException(413, "file exceeds max_upload_bytes")
                    checksum.update(chunk)
                    await asyncio.to_thread(target.write, chunk)
            if not size:
                raise HTTPException(422, "empty file")
            resolved = Resolved(
                filename=file.filename or "recording",
                input_sha256=checksum.hexdigest(),
                options=parameters,
                deployment=jobs.deployment,
                models={
                    name: {
                        "config": i.spec.model_dump(mode="json"),
                        "fingerprint": i.fingerprint,
                        "download_script": (i.directory / "download_model.sh").read_text(),
                        "run_script": (i.directory / "run").read_text(),
                    }
                    for name, i in runtime.instances.items()
                },
                config=config.model_dump(mode="json"),
            )
            async with submission_lock:
                directory = jobs.root / job
                if directory.exists():
                    previous = Resolved.model_validate_json(
                        (directory / "resolved.json").read_text()
                    )
                    if (
                        previous.input_sha256 != resolved.input_sha256
                        or previous.options != parameters
                        or previous.deployment != jobs.deployment
                    ):
                        raise HTTPException(
                            409, "idempotency key belongs to a different input or deployment"
                        )
                    return jobs.status(job)
                status = Status(id=job)
                atomic_text(staging / "resolved.json", resolved.model_dump_json(indent=2))
                atomic_text(staging / "status.json", status.model_dump_json(indent=2))
                staging.rename(directory)
                await jobs.queue.put(job)
                return status
        finally:
            await file.close()
            if staging.exists():
                shutil.rmtree(staging)

    def job_directory(job: str) -> Path:
        if (
            not re.fullmatch(r"[a-f0-9]{32}", job)
            or not (jobs.root / job / "status.json").is_file()
        ):
            raise HTTPException(404, "job not found")
        return jobs.root / job

    @app.get("/jobs/{job}")
    def status(job: str) -> Status:
        job_directory(job)
        return jobs.status(job)

    @app.get("/jobs/{job}/artifacts/{name}")
    def artifact(job: str, name: str) -> FileResponse:
        directory = job_directory(job) / "artifacts"
        if Path(name).name != name or not name.endswith((".md", ".json")):
            raise HTTPException(404, "artifact not found")
        path = directory / name
        if not path.is_file():
            raise HTTPException(404, "artifact not ready")
        return FileResponse(path, filename=name)

    @app.get("/jobs/{job}/download")
    def download(job: str) -> FileResponse:
        directory = job_directory(job)
        if jobs.status(job).state not in ("completed", "partial_failed", "failed"):
            raise HTTPException(409, "job is still running")
        return FileResponse(directory / "transcripts.zip", filename=f"{job}.zip")

    return app


def main(
    config: Path = Path("/opt/asr/server/server.yaml"),
    host: str = "0.0.0.0",  # noqa: S104 - published container API
    port: int = 8080,
) -> None:
    uvicorn.run(create_app(read_config(config)), host=host, port=port, workers=1)


if __name__ == "__main__":
    typer.run(main)
