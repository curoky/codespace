import zipfile
from pathlib import Path

from server.storage import atomic_text
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


def save(directory: Path, result: Transcript) -> None:
    atomic_text(directory / f"{result.recipe}.json", result.model_dump_json(indent=2))
    atomic_text(directory / f"{result.recipe}.md", markdown(result))


def index(directory: Path, statuses: dict[str, str]) -> None:
    lines = [
        "# 转录结果",
        "",
        "各方案独立输出，不按准确性排名；不同方案的 speaker 标签不能直接互认。",
        "",
    ]
    for recipe, status in statuses.items():
        lines.append(f"- [{recipe}]({recipe}.md) · {status} · [JSON]({recipe}.json)")
    atomic_text(directory / "index.md", "\n".join(lines) + "\n")


def bundle(directory: Path) -> Path:
    target = directory.parent / "transcripts.zip"
    temporary = target.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(directory.iterdir()):
            if path.is_file():
                output.write(path, path.name)
    temporary.replace(target)
    return target
