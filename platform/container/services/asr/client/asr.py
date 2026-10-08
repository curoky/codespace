# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx==0.28.1", "typer==0.27.2"]
# ///
import asyncio
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated

import httpx
import typer


def extract(archive: Path, destination: Path) -> bool:
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if Path(name).name != name or not name.endswith((".md", ".json")):
                raise ValueError("server returned an invalid artifact path")
        completed = all(
            json.loads(bundle.read(name))["status"] == "completed"
            for name in bundle.namelist()
            if name.endswith(".json") and name not in {"evidence.json", "trace.json"}
        )
        bundle.extractall(destination)
    return completed


async def process(
    client: httpx.AsyncClient,
    source: Path,
    destination: Path,
    *,
    options: str,
    overwrite: bool,
) -> bool:
    if destination.exists() and not overwrite:
        raise FileExistsError(f"{destination} 已存在；使用 --overwrite 重新转录并覆盖")
    destination.parent.mkdir(parents=True, exist_ok=True)
    typer.echo(f"{source}: 转录中")
    with tempfile.TemporaryDirectory(prefix=".asr-", dir=destination.parent) as temporary:
        archive = Path(temporary) / "result.zip"
        with source.open("rb") as audio:
            async with client.stream(
                "POST",
                "/transcribe",
                data={"options": options},
                files={"file": (source.name, audio)},
                timeout=httpx.Timeout(None, connect=30),
            ) as response:
                response.raise_for_status()
                with archive.open("wb") as output:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        await asyncio.to_thread(output.write, chunk)
        result = Path(temporary) / "result"
        result.mkdir()
        completed = await asyncio.to_thread(extract, archive, result)
        if destination.exists():
            shutil.rmtree(destination)
        result.rename(destination)
    typer.echo(f"{source}: {'完成' if completed else '部分方案失败，请查看索引'} → {destination}")
    return completed


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
    async with httpx.AsyncClient(base_url=server.rstrip("/")) as client:

        async def one(path: Path) -> bool:
            async with limit:
                relative = Path(path.name) if source.is_file() else path.relative_to(source)
                try:
                    return await process(
                        client, path, out / relative, options=options, overwrite=overwrite
                    )
                except (httpx.HTTPError, OSError, ValueError, zipfile.BadZipFile) as exc:
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
