import io
import json
import zipfile

from pydantic import JsonValue

from server.tracing import TraceDocument
from server.transcript import Transcript


def timestamp(ms: int) -> str:
    seconds, milliseconds = divmod(ms, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


def markdown(result: Transcript) -> str:
    lines = [f"# {result.recipe}", "", f"状态：{result.status}", ""]
    if result.error:
        lines.extend([f"> 未完成：{result.error}", ""])
    for warning in result.warnings:
        lines.extend([f"> {warning}", ""])
    for segment in result.segments:
        speaker = "/".join(segment.speakers) or "说话人未知"
        flags = " · 待核对：" + ", ".join(segment.flags) if segment.flags else ""
        lines.extend(
            [
                f"**[{timestamp(segment.start_ms)}–{timestamp(segment.end_ms)}] {speaker}{flags}**",
                "",
                segment.text,
                "",
            ]
        )
    if not result.segments and result.status == "completed":
        lines.extend(["未检测到可转写语音。", ""])
    return "\n".join(lines)


def bundle(
    results: list[Transcript], evidence: dict[str, JsonValue], trace: TraceDocument
) -> bytes:
    lines = [
        "# 转录结果",
        "",
        "各方案独立输出，不按准确性排名；不同方案的 speaker 标签不能直接互认。",
        "",
    ]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for result in results:
            recipe = result.recipe
            lines.append(f"- [{recipe}]({recipe}.md) · {result.status} · [JSON]({recipe}.json)")
            output.writestr(f"{recipe}.json", result.model_dump_json(indent=2))
            output.writestr(f"{recipe}.md", markdown(result))
        lines.extend(
            [
                "",
                "[执行追踪与工程指标](trace.json) · [共享识别证据与参数](evidence.json)",
                "",
            ]
        )
        output.writestr("index.md", "\n".join(lines))
        output.writestr("evidence.json", json.dumps(evidence, ensure_ascii=False, indent=2))
        output.writestr("trace.json", trace.model_dump_json(indent=2, exclude_none=True))
    return buffer.getvalue()
