# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx==0.28.1", "typer==0.27.2", "pydantic==2.13.5"]
# ///
import asyncio
import hashlib
import json
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Annotated

import httpx
import typer
from pydantic import BaseModel, ConfigDict, Field


class Status(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    state: str
    stage: str
    recipes: dict[str, str]
    error: str | None = None


class State(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: str
    key: str
    job: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)


def checksum(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save(path: Path, state: State) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(state.model_dump_json(indent=2))
    temporary.replace(path)


def extract(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name = info.filename
            if Path(name).name != name or not name.endswith((".md", ".json")):
                raise ValueError("server returned an invalid artifact path")
        for info in bundle.infolist():
            target = destination / info.filename
            temporary = target.with_suffix(target.suffix + ".tmp")
            with bundle.open(info) as source, temporary.open("wb") as output:
                while chunk := source.read(1024 * 1024):
                    output.write(chunk)
            temporary.replace(target)


async def process(
    client: httpx.AsyncClient,
    source: Path,
    destination: Path,
    *,
    deployment: str,
    options: str,
    overwrite: bool,
) -> bool:
    destination.mkdir(parents=True, exist_ok=True)
    identity = hashlib.sha256(
        json.dumps(
            {
                "sha256": await asyncio.to_thread(checksum, source),
                "options": options,
                "server": str(client.base_url),
                "deployment": deployment,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    state_path = destination / ".asr-state.json"
    previous = State.model_validate_json(state_path.read_text()) if state_path.is_file() else None
    if previous and previous.identity == identity and not overwrite:
        state = previous
    else:
        nonce = uuid.uuid4().hex if overwrite else ""
        state = State(
            identity=identity, key=hashlib.sha256((identity + nonce).encode()).hexdigest()
        )
        save(state_path, state)
    if not state.job:
        with source.open("rb") as audio:
            response = await client.post(
                "/jobs",
                data={"options": options},
                files={"file": (source.name, audio)},
                headers={"Idempotency-Key": state.key},
                timeout=3600,
            )
        response.raise_for_status()
        state.job = Status.model_validate_json(response.content).id
        save(state_path, state)
    last_stage = ""
    failures = 0
    while True:
        try:
            response = await client.get(f"/jobs/{state.job}")
            response.raise_for_status()
            status = Status.model_validate_json(response.content)
            failures = 0
        except httpx.TransportError:
            failures += 1
            if failures >= 5:
                raise
            await asyncio.sleep(min(2**failures, 15))
            continue
        if status.stage != last_stage:
            typer.echo(f"{source}: {status.stage}")
            last_stage = status.stage
        if status.state in ("completed", "partial_failed", "failed"):
            break
        await asyncio.sleep(2)
    valid = bool(state.artifacts)
    for name, digest in state.artifacts.items():
        if (
            not (destination / name).is_file()
            or await asyncio.to_thread(checksum, destination / name) != digest
        ):
            valid = False
            break
    if not valid:
        with tempfile.TemporaryDirectory(
            prefix=".asr-download-", dir=destination.parent
        ) as temporary:
            archive = Path(temporary) / "result.zip"
            async with client.stream(
                "GET", f"/jobs/{state.job}/download", timeout=3600
            ) as response:
                response.raise_for_status()
                with archive.open("wb") as output:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        await asyncio.to_thread(output.write, chunk)
            await asyncio.to_thread(extract, archive, destination)
        state.artifacts = {
            path.name: await asyncio.to_thread(checksum, path)
            for path in destination.iterdir()
            if path.is_file() and not path.name.startswith(".") and path.suffix in (".md", ".json")
        }
        save(state_path, state)
    typer.echo(f"{source}: {status.state} → {destination}")
    return status.state == "completed"


async def run(
    source: Path, server: str, out: Path, parallel: int, options: str, overwrite: bool
) -> bool:
    files = (
        [source]
        if source.is_file()
        else sorted(
            path
            for path in source.rglob("*")
            if path.is_file()
            and path.suffix.lower()
            in {".wav", ".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".webm", ".aac"}
        )
    )
    if not files:
        raise ValueError("没有找到录音文件")
    limit = asyncio.Semaphore(parallel)
    async with httpx.AsyncClient(base_url=server.rstrip("/"), timeout=30) as client:
        health = await client.get("/health")
        health.raise_for_status()
        deployment = str(health.json()["deployment"])

        async def one(path: Path) -> bool:
            async with limit:
                relative = Path(path.name) if source.is_file() else path.relative_to(source)
                try:
                    return await process(
                        client,
                        path,
                        out / relative,
                        deployment=deployment,
                        options=options,
                        overwrite=overwrite,
                    )
                except (httpx.HTTPError, OSError, ValueError) as exc:
                    typer.echo(f"{path}: {exc}", err=True)
                    return False

        return all(await asyncio.gather(*(one(path) for path in files)))


def main(
    source: Annotated[Path, typer.Argument(exists=True)],
    server: Annotated[str, typer.Option()] = "http://localhost:8080",
    out: Annotated[Path, typer.Option()] = Path("texts"),
    parallel: Annotated[int, typer.Option(min=1)] = 2,
    num_speakers: Annotated[int | None, typer.Option(min=1)] = None,
    hotword: Annotated[list[str] | None, typer.Option()] = None,
    separate_channels: bool = False,
    vad_off: bool = False,
    overwrite: bool = False,
) -> None:
    options = json.dumps(
        {
            "num_speakers": num_speakers,
            "hotwords": hotword or [],
            "separate_channels": separate_channels,
            "vad_mode": "off" if vad_off else "on",
        }
    )
    try:
        success = asyncio.run(
            run(source.resolve(), server, out.resolve(), parallel, options, overwrite)
        )
    except (httpx.HTTPError, OSError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    if not success:
        raise typer.Exit(1)


if __name__ == "__main__":
    typer.run(main)
