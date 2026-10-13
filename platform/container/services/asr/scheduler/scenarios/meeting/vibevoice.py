import asyncio
from collections import defaultdict
from functools import cache
from pathlib import Path

from protocol import InferenceRequest, Span
from scheduler.audio import cut, windows
from scheduler.config import ChunkConfig
from scheduler.inference import Inference
from scheduler.options import Options
from scheduler.transcript import Segment, Transcript


def overlap(a: int, b: int, span: Span) -> int:
    return max(0, min(b, span.end_ms) - max(a, span.start_ms))


def mapped_identity(local: list[Span], global_spans: list[Span]) -> dict[str, str | None]:
    votes: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for segment in local:
        if segment.speaker is None:
            continue
        for reference in global_spans:
            start, end = (
                max(segment.start_ms, reference.start_ms),
                min(segment.end_ms, reference.end_ms),
            )
            if start >= end or reference.speaker is None:
                continue
            if any(
                other.speaker != reference.speaker and overlap(start, end, other)
                for other in global_spans
            ):
                continue
            votes[segment.speaker][reference.speaker] += end - start
    local_speakers = sorted({s.speaker for s in local if s.speaker})
    global_speakers = sorted({s.speaker for s in global_spans if s.speaker})

    @cache
    def assign(index: int, used: int) -> tuple[int, tuple[tuple[str, str], ...]]:
        if index == len(local_speakers):
            return 0, ()
        best_score, best_pairs = assign(index + 1, used)
        local_speaker = local_speakers[index]
        for position, global_speaker in enumerate(global_speakers):
            if used & (1 << position):
                continue
            evidence = votes[local_speaker][global_speaker]
            if not evidence:
                continue
            tail_score, tail_pairs = assign(index + 1, used | (1 << position))
            candidate = evidence + tail_score
            if candidate > best_score:
                best_score = candidate
                best_pairs = ((local_speaker, global_speaker), *tail_pairs)
        return best_score, best_pairs

    mapping = dict(assign(0, 0)[1])
    return {speaker: mapping.get(speaker) for speaker in local_speakers}


async def transcribe(
    inference: Inference, audio: Path, duration: int, options: Options
) -> Transcript:
    diarization = asyncio.create_task(
        inference.call(
            "pyannote-community-1",
            InferenceRequest(audio=str(audio), num_speakers=options.num_speakers),
            step="speaker_anchor",
        )
    )
    detection = asyncio.create_task(
        inference.call("firered-vad", InferenceRequest(audio=str(audio)), step="vad")
    )
    chunks = windows(
        [Span(start_ms=0, end_ms=duration)],
        duration,
        ChunkConfig(target_seconds=176, padding_ms=0),
    )

    async def window(start: int, end: int) -> list[Segment]:
        clip = inference.work / f"joint-{start}-{end}.wav"
        async with inference.models.cpu:
            await asyncio.to_thread(cut, audio, clip, start, end)
        response = await inference.call(
            "vibevoice",
            InferenceRequest(
                audio=str(clip),
                hotwords=options.hotwords,
                mode="meeting",
                language=options.language,
            ),
            step="joint",
        )
        activity = (await detection).spans
        if not response.spans:
            raise ValueError("joint model returned no segments")
        if any(span.end_ms > end - start + 100 for span in response.spans):
            raise ValueError("joint model timestamp exceeds audio")
        active_end = max(
            (
                min(span.end_ms, end)
                for span in activity
                if span.end_ms > start and span.start_ms < end
            ),
            default=start,
        )
        if max(span.end_ms + start for span in response.spans) < active_end - 2000:
            raise ValueError("joint transcript does not cover active tail")
        local = [
            span.model_copy(
                update={"start_ms": span.start_ms + start, "end_ms": span.end_ms + start}
            )
            for span in response.spans
        ]

        names: dict[str, str] = {}
        speakers = []
        for span in sorted((await diarization).spans, key=lambda span: span.start_ms):
            name = names.setdefault(span.speaker or "", f"S{len(names) + 1:02d}")
            speakers.append(span.model_copy(update={"speaker": name}))
        mapping = mapped_identity(local, speakers)
        parts = []
        for span in local:
            identity = mapping.get(span.speaker or "")
            parts.append(
                Segment(
                    start_ms=span.start_ms,
                    end_ms=span.end_ms,
                    text=span.text,
                    speakers=[identity] if identity else [],
                    flags=[] if identity else ["speaker_unknown"],
                )
            )
        return parts

    batches = await asyncio.gather(*(window(chunk.start_ms, chunk.end_ms) for chunk in chunks))
    result = Transcript(recipe="meeting/vibevoice", activity=(await detection).spans)
    result.segments = [segment for batch in batches for segment in batch]
    result.segments.sort(key=lambda segment: segment.start_ms)
    result.speakers = [
        Span(start_ms=segment.start_ms, end_ms=segment.end_ms, speaker=segment.speakers[0])
        for segment in result.segments
        if segment.speakers
    ]
    return result
