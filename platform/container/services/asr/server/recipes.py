import asyncio
import logging
import re
from pathlib import Path
from typing import Literal

import httpx
from pydantic import Field, JsonValue

from protocol import InferenceRequest, InferenceResult, Record, Span, Token
from server.audio import Window, cut, union, windows
from server.config import ChunkConfig, Config
from server.inference import Inference
from server.transcript import (
    Segment,
    Transcript,
    align_text,
    choose,
    differences,
    mapped_identity,
    normalized,
    owners,
    plain,
    punctuation_content,
    rename_speakers,
    utterances,
)


class Options(Record):
    num_speakers: int | None = Field(default=None, ge=1)
    hotwords: list[str] = Field(default_factory=list, max_length=200)
    vad_mode: Literal["on", "off"] = "on"
    separate_channels: bool = False


RECIPE_IDS = (
    "01-qwen-fusion",
    "02-firered-fusion",
    "03-moss-td",
    "04-vibevoice",
    "05-qwen-nemotron",
)


class Pipeline:
    def __init__(
        self, config: Config, inference: Inference, audio: Path, duration: int, options: Options
    ) -> None:
        self.config, self.inference, self.audio = config, inference, audio
        self.duration, self.options = duration, options
        self.candidates: dict[str, dict[str, str]] = {}
        self.reviewed: dict[str, dict[str, str]] = {}
        self.errors: dict[str, str] = {}
        self.activity: list[Span] = []
        self.speakers: list[Span] = []
        self.chunks: list[Window] = []

    async def clip(self, window: Window) -> Path:
        path = self.inference.work / f"clip-{window.start_ms}-{window.end_ms}.wav"
        if not path.is_file():
            await asyncio.to_thread(cut, self.audio, path, window.start_ms, window.end_ms)
        return path

    async def recognize(self, model: str, window: Window) -> InferenceResult:
        path = await self.clip(window)
        result = await self.inference.call(
            model,
            InferenceRequest(
                audio=str(path),
                hotwords=self.options.hotwords,
            ),
        )
        for span in result.spans:
            if span.end_ms > window.end_ms - window.start_ms + 100:
                raise ValueError(f"{model}: timestamp outside input window")
        return result

    async def prepare(self) -> None:
        diarized = await self.inference.call(
            self.config.diarizer,
            InferenceRequest(
                audio=str(self.audio),
                num_speakers=self.options.num_speakers,
            ),
        )
        self.speakers = rename_speakers(diarized.spans)
        if self.options.vad_mode == "off":
            self.activity = [Span(start_ms=0, end_ms=self.duration)]
        else:
            detections = await asyncio.gather(
                *[
                    self.inference.call(model, InferenceRequest(audio=str(self.audio)))
                    for model in self.config.vad
                ]
            )
            self.activity = union(
                self.speakers + [span for result in detections for span in result.spans]
            )
        self.chunks = windows(self.activity, self.duration, self.config.chunking)

    async def align(self, text: str, window: Window) -> list[Token]:
        if not normalized(text):
            return []
        result = await self.inference.call(
            self.config.aligner,
            InferenceRequest(
                audio=str(await self.clip(window)),
                text=text,
            ),
        )
        return align_text(
            text, result.tokens, offset=window.start_ms, limit=window.end_ms - window.start_ms
        )

    async def first_pass(self) -> None:
        for model in ("qwen3-asr-1.7b", "firered-llm", "sensevoice", "paraformer"):
            for window in self.chunks:
                key = window.model_dump_json()
                candidates = self.candidates.setdefault(key, {})
                try:
                    result = await self.recognize(model, window)
                    candidates[model] = plain(result.text)
                except Exception as exc:
                    logging.exception("first pass %s failed", model)
                    self.errors[f"first_pass:{model}:{key}"] = str(exc)

    async def review(self, window: Window, candidates: dict[str, str]) -> dict[str, str]:
        key = window.model_dump_json()
        if key in self.reviewed:
            return self.reviewed[key]
        has_dispute = len({normalized(text) for text in candidates.values()}) > 1
        suspicious = any(
            not text.strip() or re.search(r"(.{2,8})\1{3,}", text) for text in candidates.values()
        )
        if not has_dispute and not suspicious:
            return {}
        extra = max(
            0, (self.config.chunking.max_seconds * 1000 - (window.end_ms - window.start_ms)) // 2
        )
        expanded = Window(
            start_ms=max(0, window.start_ms - extra),
            end_ms=min(self.duration, window.end_ms + extra),
            core_start_ms=window.core_start_ms,
            core_end_ms=window.core_end_ms,
        )
        reviews: dict[str, str] = {}
        for model in ("qwen3-asr-1.7b", "firered-llm", "whisper-large-v3", "moss-audio"):
            if model == "moss-audio" and len({normalized(t) for t in reviews.values()}) == 1:
                break
            try:
                result = await self.recognize(model, expanded)
                tokens = await self.align(plain(result.text), expanded)
            except Exception as exc:
                logging.exception("review %s failed", model)
                self.errors[f"review:{model}:{key}"] = str(exc)
                continue
            if any(t.start_ms is None for t in tokens):
                continue
            reviews[model] = "".join(
                t.text
                for t in tokens
                if t.start_ms is not None
                and t.end_ms is not None
                and window.start_ms <= (t.start_ms + t.end_ms) / 2 < window.end_ms
            )
        self.reviewed[key] = reviews
        return reviews

    async def finalize_segment(
        self, segment: Segment, window: Window, speakers: list[Span], *, punctuate: bool = True
    ) -> list[Segment]:
        if punctuate and self.config.punctuation and normalized(segment.text):
            result = await self.inference.call(
                self.config.punctuation, InferenceRequest(text=segment.text)
            )
            if punctuation_content(result.text) == punctuation_content(segment.text):
                segment.text = result.text
            else:
                segment.flags.append("punctuation_changed_content_rejected")
        segment.tokens = await self.align(segment.text, window)
        if any(t.start_ms is None for t in segment.tokens):
            segment.flags.append("alignment_failed")
            if not punctuate and (
                window.core_start_ms != window.start_ms or window.core_end_ms != window.end_ms
            ):
                raise ValueError("joint boundary alignment failed; cannot deduplicate safely")
        else:
            segment.tokens = [
                t
                for t in segment.tokens
                if t.start_ms is not None
                and t.end_ms is not None
                and window.core_start_ms <= (t.start_ms + t.end_ms) / 2 < window.core_end_ms
            ]
            segment.text = "".join(t.text for t in segment.tokens)
        return utterances(segment, speakers)

    async def fusion(self, recipe: str, primary: str) -> Transcript:
        result = Transcript(recipe=recipe, activity=self.activity, speakers=self.speakers)
        families = {name: i.spec.family for name, i in self.inference.scheduler.instances.items()}
        for window in self.chunks:
            candidates = self.candidates[window.model_dump_json()]
            if primary not in candidates:
                raise ValueError(f"{primary}: primary transcript is unavailable")
            original = candidates[primary]
            reviews = await self.review(window, candidates)
            protected = bool(
                re.search(r"[0-9零一二三四五六七八九十百千万亿两]|[A-Z][a-z]", original)
            )
            protected |= any(word in original for word in self.options.hotwords)
            protected |= len(owners(window.core_start_ms, window.core_end_ms, self.speakers)) > 1
            text, decision = choose(original, primary, reviews, families, protected=protected)
            flags = ["disagreement"] if differences(original, candidates) else []
            if len(candidates) < 4:
                flags.append("crosscheck_incomplete")
            if reviews and decision in ("primary", "unresolved"):
                flags.append("needs_review")
            segment = Segment(
                start_ms=window.core_start_ms,
                end_ms=window.core_end_ms,
                text=text,
                candidates=candidates,
                reviews=reviews,
                decision=decision,
                flags=flags,
            )
            result.segments.extend(await self.finalize_segment(segment, window, self.speakers))
        return result

    async def joint(self, recipe: str, model: str) -> Transcript:
        result = Transcript(recipe=recipe, activity=self.activity, speakers=self.speakers)
        maximum = self.inference.scheduler.instances[model].spec.max_audio_seconds
        config = ChunkConfig(target_seconds=maximum - 4, max_seconds=maximum, padding_ms=1000)

        async def transcribe(window: Window, depth: int = 0) -> list[Segment]:
            try:
                raw = await self.recognize(model, window)
                active_ends = [
                    min(s.end_ms, window.core_end_ms)
                    for s in self.activity
                    if s.end_ms > window.core_start_ms and s.start_ms < window.core_end_ms
                ]
                last_end = max((s.end_ms + window.start_ms for s in raw.spans), default=0)
                if active_ends and last_end < max(active_ends) - 2000:
                    raise ValueError(f"{model}: active tail is not covered")
                return await assemble(raw, window)
            except (ValueError, httpx.HTTPError) as exc:
                if depth >= 2 or window.core_end_ms - window.core_start_ms < 30000:
                    raise
                result.warnings.append(f"joint_window_retry:{window.start_ms}:{exc}")
                middle = (window.core_start_ms + window.core_end_ms) // 2
                parts = []
                for start, end in ((window.core_start_ms, middle), (middle, window.core_end_ms)):
                    parts.extend(
                        await transcribe(
                            Window(
                                start_ms=max(window.start_ms, start - 1000),
                                end_ms=min(window.end_ms, end + 1000),
                                core_start_ms=start,
                                core_end_ms=end,
                            ),
                            depth + 1,
                        )
                    )
                return parts

        async def assemble(raw: InferenceResult, window: Window) -> list[Segment]:
            parts = []
            local = [
                s.model_copy(
                    update={
                        "start_ms": s.start_ms + window.start_ms,
                        "end_ms": s.end_ms + window.start_ms,
                    }
                )
                for s in raw.spans
            ]
            mapping = mapped_identity(local, self.speakers)
            for span in local:
                if span.end_ms <= window.core_start_ms or span.start_ms >= window.core_end_ms:
                    continue
                aligned_window = Window(
                    start_ms=span.start_ms,
                    end_ms=span.end_ms,
                    core_start_ms=max(span.start_ms, window.core_start_ms),
                    core_end_ms=min(span.end_ms, window.core_end_ms),
                )
                aligner_limit = self.inference.scheduler.instances[
                    self.config.aligner
                ].spec.max_audio_seconds
                if span.end_ms - span.start_ms > aligner_limit * 1000:
                    raise ValueError(f"{model}: joint segment exceeds alignment window budget")
                speaker = mapping.get(span.speaker or "")
                speakers = [Span(start_ms=span.start_ms, end_ms=span.end_ms, speaker=speaker)]
                segment = Segment(
                    start_ms=span.start_ms,
                    end_ms=span.end_ms,
                    text=span.text,
                    flags=[] if speaker else ["joint_identity_unresolved"],
                )
                for chunk in self.chunks:
                    if chunk.core_end_ms <= span.start_ms or chunk.core_start_ms >= span.end_ms:
                        continue
                    candidates = self.candidates.get(chunk.model_dump_json(), {})
                    if len({normalized(t) for t in candidates.values()}) > 1:
                        segment.flags.append("crosscheck_disagreement_in_interval")
                        break
                parts.extend(
                    await self.finalize_segment(segment, aligned_window, speakers, punctuate=False)
                )
            return parts

        for window in windows([Span(start_ms=0, end_ms=self.duration)], self.duration, config):
            result.segments.extend(await transcribe(window))
        if self.errors:
            result.warnings.append("crosscheck_incomplete")
        return result

    async def nemotron(self, source: Transcript) -> Transcript:
        result = source.model_copy(deep=True, update={"recipe": "05-qwen-nemotron"})
        count = self.options.num_speakers
        observed = len({s.speaker for s in self.speakers if s.speaker})
        if count is not None and count > 8:
            result.status, result.error = (
                "failed",
                "out_of_scope: Nemotron supports at most 8 identities",
            )
            result.segments = []
            return result
        result.warnings.append(
            "suspected_out_of_scope"
            if observed > 8
            else ("unverified_max_8" if count is None else "max_8")
        )
        diarized = await self.inference.call(
            "nemotron-diarization", InferenceRequest(audio=str(self.audio))
        )
        result.speakers = rename_speakers(diarized.spans)
        result.segments = [
            part
            for segment in source.segments
            for part in utterances(segment.model_copy(deep=True), result.speakers)
        ]
        return result

    def evidence(self) -> dict[str, JsonValue]:
        return {
            "raw_responses": self.inference.records,
            "errors": dict[str, JsonValue](self.errors),
            "candidates": {
                key: dict[str, JsonValue](value) for key, value in self.candidates.items()
            },
            "reviews": {key: dict[str, JsonValue](value) for key, value in self.reviewed.items()},
        }
