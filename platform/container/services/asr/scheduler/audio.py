import wave
from array import array
from pathlib import Path

from pydantic import Field

from protocol import Record, Span
from scheduler.config import ChunkConfig


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
                start_ms=max(0, span.start_ms - config.padding_ms),
                end_ms=min(duration, span.end_ms + config.padding_ms),
            )
            for span in spans
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


def inspect(path: Path) -> tuple[int, int]:
    with wave.open(str(path), "rb") as audio:
        if audio.getframerate() != 16000 or audio.getsampwidth() != 2:
            raise ValueError("expected 16 kHz 16-bit PCM WAV")
        return round(audio.getnframes() * 1000 / audio.getframerate()), audio.getnchannels()


def cut(source: Path, target: Path, start_ms: int, end_ms: int) -> None:
    with wave.open(str(source), "rb") as audio, wave.open(str(target), "wb") as output:
        output.setparams(audio.getparams())
        audio.setpos(start_ms * 16)
        output.writeframes(audio.readframes((end_ms - start_ms) * 16))


def extract_channel(source: Path, target: Path, channel: int) -> None:
    with wave.open(str(source), "rb") as audio, wave.open(str(target), "wb") as output:
        channels = audio.getnchannels()
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(audio.getframerate())
        while payload := audio.readframes(160000):
            values = array("h", payload)
            output.writeframes(array("h", values[channel::channels]).tobytes())
