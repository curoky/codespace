# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx==0.28.1", "pydantic==2.13.5", "typer==0.27.2"]
# ///
import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Annotated, Literal, cast

import httpx
import typer
from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ResponseRecord(BaseModel):
    model_config = ConfigDict(extra="allow")


class Segment(ResponseRecord):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    text: str
    speakers: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class Result(ResponseRecord):
    recipe: str
    status: Literal["completed", "failed"]
    error: str | None = None
    warnings: list[str] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["phase", "model"]
    name: str
    channel: str | None = None
    status: Literal["completed", "failed"]
    started_ms: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    model: str | None = None
    cache_hit: bool | None = None
    gpu_ids: list[str] = Field(default_factory=list)
    gpu_indices: list[str] = Field(default_factory=list)
    model_queue_ms: int | None = Field(default=None, ge=0)
    cpu_queue_ms: int | None = Field(default=None, ge=0)
    inference_ms: int | None = Field(default=None, ge=0)
    input_summary: dict[str, JsonValue] = Field(default_factory=dict)
    output_summary: dict[str, JsonValue] = Field(default_factory=dict)
    error: str | None = None


class GPUDeviceSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    index: str
    gpu_percent: int = Field(ge=0, le=100)
    memory_percent: int = Field(ge=0, le=100)
    memory_used_mib: int = Field(ge=0)
    power_watts: float | None = Field(default=None, ge=0)


class GPUUtilizationSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp_ms: int = Field(ge=0)
    devices: list[GPUDeviceSample]


class TraceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    status: Literal["completed", "partial"]
    duration_ms: int = Field(ge=0)
    events: list[TraceEvent]
    gpu_sample_interval_ms: Literal[1000]
    gpu_samples: list[GPUUtilizationSample]
    gpu_sampling_error: str | None = None


class TranscriptionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[Result]
    evidence: dict[str, JsonValue]
    trace: TraceDocument


def timestamp(ms: int) -> str:
    seconds, milliseconds = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


def markdown(result: Result) -> str:
    lines = [f"# {result.recipe}", "", f"状态：{result.status}", ""]
    if result.error is not None:
        lines.extend([f"> 未完成：{result.error}", ""])
    for warning in result.warnings:
        lines.extend([f"> {warning}", ""])
    for segment in result.segments:
        speaker = "/".join(segment.speakers) or "说话人未知"
        suffix = " · 待核对：" + ", ".join(segment.flags) if segment.flags else ""
        lines.extend(
            [
                f"**[{timestamp(segment.start_ms)}–{timestamp(segment.end_ms)}] "
                f"{speaker}{suffix}**",
                "",
                segment.text,
                "",
            ]
        )
    if not result.segments and result.status == "completed":
        lines.extend(["未检测到可转写语音。", ""])
    return "\n".join(lines)


def trace_report(trace: TraceDocument) -> str:
    """把严格校验后的 trace 嵌入可离线打开的 client-side viewer。"""
    template = Path(__file__).with_name("trace.html").read_text()
    data = trace.model_dump_json(exclude_none=True)
    safe = (
        data.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    marker = "__ASR_TRACE_DATA__"
    if template.count(marker) != 1:
        raise ValueError("trace viewer template must contain exactly one data marker")
    return template.replace(marker, safe)


def write_response(payload: JsonValue, destination: Path) -> bool:
    """严格校验服务响应，在临时目录内生成一套可原子发布的本地产物。"""
    response = TranscriptionResponse.model_validate(payload)
    recipes: set[str] = set()
    lines = [
        "# 转录结果",
        "",
        "各方案独立输出，不按准确性排名；不同方案的 speaker 标签不能直接互认。",
        "",
    ]
    completed = True
    for result in response.results:
        recipe = result.recipe
        status = result.status
        if not recipe or Path(recipe).name != recipe or recipe in recipes:
            raise ValueError("server returned an invalid or duplicate recipe")
        recipes.add(recipe)
        completed &= status == "completed"
        lines.append(f"- [{recipe}]({recipe}.md) · {status} · [JSON]({recipe}.json)")
        document = result.model_dump(mode="json")
        document["evidence"] = "evidence.json"
        (destination / f"{recipe}.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2)
        )
        (destination / f"{recipe}.md").write_text(markdown(result))
    lines.extend(
        [
            "",
            "[执行追踪可视化](trace.html) · [原始 Trace JSON](trace.json) · "
            "[共享识别证据与参数](evidence.json)",
            "",
        ]
    )
    (destination / "index.md").write_text("\n".join(lines))
    (destination / "evidence.json").write_text(
        json.dumps(response.evidence, ensure_ascii=False, indent=2)
    )
    (destination / "trace.json").write_text(
        json.dumps(
            response.trace.model_dump(mode="json", exclude_none=True), ensure_ascii=False, indent=2
        )
    )
    (destination / "trace.html").write_text(trace_report(response.trace))
    return completed


async def process(
    client: httpx.AsyncClient,
    source: Path,
    destination: Path,
    *,
    options: str,
    overwrite: bool,
) -> bool:
    """完成一次长连接转写，全部文件就绪后再替换目标目录。"""
    if destination.exists() and not overwrite:
        raise FileExistsError(f"{destination} 已存在；使用 --overwrite 重新转录并覆盖")
    destination.parent.mkdir(parents=True, exist_ok=True)
    typer.echo(f"{source}: 转录中")
    with source.open("rb") as audio:
        response = await client.post(
            "/transcribe",
            data={"options": options},
            files={"file": (source.name, audio)},
            timeout=httpx.Timeout(None, connect=30),
        )
    response.raise_for_status()
    payload = cast(JsonValue, response.json())
    with tempfile.TemporaryDirectory(prefix=".asr-", dir=destination.parent) as temporary:
        result = Path(temporary) / "result"
        result.mkdir()
        completed = await asyncio.to_thread(write_response, payload, result)
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
