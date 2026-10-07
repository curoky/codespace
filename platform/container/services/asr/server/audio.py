import asyncio
import json
import wave
from pathlib import Path

from pydantic import Field

from ops.processes import command
from protocol import Record, Span
from server.config import ChunkConfig


class Window(Record):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    core_start_ms: int = Field(ge=0)
    core_end_ms: int = Field(ge=0)


def union(spans: list[Span]) -> list[Span]:
    merged: list[Span] = []
    for span in sorted(spans, key=lambda s: s.start_ms):
        if merged and span.start_ms <= merged[-1].end_ms:
            merged[-1].end_ms = max(merged[-1].end_ms, span.end_ms)
        else:
            merged.append(Span(start_ms=span.start_ms, end_ms=span.end_ms))
    return merged


def windows(spans: list[Span], duration: int, config: ChunkConfig) -> list[Window]:
    result = []
    padded = union(
        [
            Span(
                start_ms=max(0, s.start_ms - config.padding_ms),
                end_ms=min(duration, s.end_ms + config.padding_ms),
            )
            for s in spans
        ]
    )
    for span in padded:
        start = span.start_ms
        while start < span.end_ms:
            end = min(start + config.target_seconds * 1000, span.end_ms)
            result.append(
                Window(
                    start_ms=max(span.start_ms, start - config.padding_ms),
                    end_ms=min(span.end_ms, end + config.padding_ms),
                    core_start_ms=start,
                    core_end_ms=end,
                )
            )
            start = end
    return result


def wav_duration(path: Path) -> int:
    with wave.open(str(path), "rb") as audio:
        return round(audio.getnframes() * 1000 / audio.getframerate())


def cut(source: Path, target: Path, start_ms: int, end_ms: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    with wave.open(str(source), "rb") as audio, wave.open(str(temporary), "wb") as output:
        output.setparams(audio.getparams())
        audio.setpos(start_ms * 16)
        output.writeframes(audio.readframes((end_ms - start_ms) * 16))
    temporary.replace(target)


async def decode(source: Path, work: Path, *, channel: int | None = None) -> tuple[Path, int, str]:
    metadata = await command(
        "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)
    )
    info = json.loads(metadata)
    streams = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if not streams:
        raise ValueError("input has no audio stream")
    target = work / ("audio.wav" if channel is None else f"channel-{channel}.wav")
    if not target.is_file():
        temporary = target.with_suffix(".tmp")
        args = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(source), "-map", "0:a:0"]
        if channel is not None:
            if channel >= streams[0]["channels"]:
                raise ValueError("requested channel is absent")
            args += ["-af", f"pan=mono|c0=c{channel}"]
        args += ["-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-f", "wav", str(temporary)]
        await command(*args, timeout=3600)
        temporary.replace(target)
    duration = await asyncio.to_thread(wav_duration, target)
    if duration <= 0:
        raise ValueError("empty audio")
    return target, duration, metadata
