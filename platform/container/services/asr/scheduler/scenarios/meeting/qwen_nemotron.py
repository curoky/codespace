import asyncio
import difflib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from protocol import InferenceRequest, Span, Token
from scheduler.audio import Window, cut, union, windows
from scheduler.config import ChunkConfig
from scheduler.inference import Inference
from scheduler.options import Options
from scheduler.transcript import Segment, Transcript


def plain(text: str) -> str:
    return re.sub("<\\|[^|]+\\|>", "", text)


def normalized(text: str) -> str:
    return "".join(
        ch.lower()
        for ch in plain(text)
        if not ch.isspace() and (not unicodedata.category(ch).startswith("P"))
    )


def punctuation_content(text: str) -> str:
    return "".join(
        ch for ch in text if not ch.isspace() and not unicodedata.category(ch).startswith("P")
    )


def punctuation_input(text: str) -> str:
    raw = plain(text)
    result = []
    for index, character in enumerate(raw):
        if not unicodedata.category(character).startswith("P"):
            result.append(character)
            continue
        previous = raw[index - 1] if index else ""
        following = raw[index + 1] if index + 1 < len(raw) else ""
        if character in "，,.：:" and previous.isdigit() and following.isdigit():
            result.append(character)
    return "".join(result)


def rename_speakers(spans: list[Span]) -> list[Span]:
    names: dict[str, str] = {}
    result = []
    for span in sorted(spans, key=lambda s: (s.start_ms, s.end_ms)):
        speaker = span.speaker
        if speaker is not None:
            speaker = names.setdefault(speaker, f"S{len(names) + 1:02d}")
        result.append(span.model_copy(update={"speaker": speaker}))
    return result


def overlap(a: int, b: int, span: Span) -> int:
    return max(0, min(b, span.end_ms) - max(a, span.start_ms))


def owners(start: int | None, end: int | None, speakers: list[Span]) -> list[str]:
    if start is None or end is None:
        return []
    if start == end:
        return sorted(
            {
                span.speaker
                for span in speakers
                if span.speaker and span.start_ms <= start < span.end_ms
            }
        )
    scores: dict[str, int] = defaultdict(int)
    for span in speakers:
        if span.speaker:
            scores[span.speaker] += overlap(start, end, span)
    return sorted(
        (speaker for speaker, score in scores.items() if score >= max(1, (end - start) * 0.25))
    )


def align_text(text: str, tokens: list[Token], *, offset: int, limit: int) -> list[Token]:
    indices = [
        i
        for i, char in enumerate(text)
        if not char.isspace() and (not unicodedata.category(char).startswith("P"))
    ]
    if not tokens or normalized("".join(t.text for t in tokens)) != normalized(text):
        return [Token(text=text)] if text else []
    result = []
    consumed = 0
    previous = 0
    for token in tokens:
        consumed += len(normalized(token.text))
        boundary = indices[consumed] if consumed < len(indices) else len(text)
        start, end = (token.start_ms, token.end_ms)
        if start is not None and end is not None and (0 <= start <= end <= limit):
            start, end = (start + offset, end + offset)
        else:
            start, end = (None, None)
        result.append(Token(text=text[previous:boundary], start_ms=start, end_ms=end))
        previous = boundary
    return result


def utterances(segment: Segment, speakers: list[Span]) -> list[Segment]:
    result: list[Segment] = []
    for token in segment.tokens:
        token.speakers = owners(token.start_ms, token.end_ms, speakers)
        if not result or result[-1].speakers != token.speakers:
            result.append(
                segment.model_copy(
                    deep=True,
                    update={
                        "text": "",
                        "tokens": [],
                        "speakers": token.speakers,
                        "start_ms": token.start_ms
                        if token.start_ms is not None
                        else segment.start_ms,
                        "end_ms": token.end_ms if token.end_ms is not None else segment.end_ms,
                    },
                )
            )
        current = result[-1]
        current.text += token.text
        current.tokens.append(token)
        current.start_ms = min(
            current.start_ms, token.start_ms if token.start_ms is not None else segment.start_ms
        )
        current.end_ms = max(
            current.end_ms, token.end_ms if token.end_ms is not None else segment.end_ms
        )
        if len(token.speakers) > 1 and "overlap" not in current.flags:
            current.flags.append("overlap")
        if not token.speakers and "speaker_unknown" not in current.flags:
            current.flags.append("speaker_unknown")
    return result or [segment]


@dataclass(frozen=True)
class _Content:
    raw: str
    characters: tuple[str, ...]
    starts: tuple[int, ...]
    ends: tuple[int, ...]

    def slice(self, start: int, end: int) -> str:
        if start == end:
            return ""
        return self.raw[self.starts[start] : self.ends[end - 1]]

    def range(self, start: int, end: int) -> tuple[int, int]:
        if start == end:
            boundary = self.starts[start] if start < len(self.starts) else len(self.raw)
            return (boundary, boundary)
        return (self.starts[start], self.ends[end - 1])


@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: tuple[str, ...]
    raw_replacement: str
    replacement_protected: bool

    @property
    def signature(self) -> tuple[int, int, tuple[str, ...]]:
        return (self.start, self.end, self.replacement)


def _content(text: str) -> _Content:
    raw = plain(text)
    characters = []
    starts = []
    ends = []
    for index, character in enumerate(raw):
        if character.isspace() or unicodedata.category(character).startswith("P"):
            continue
        characters.append(character.lower())
        starts.append(index)
        ends.append(index + 1)
    return _Content(raw, tuple(characters), tuple(starts), tuple(ends))


def _protected_positions(content: _Content, hotwords: tuple[str, ...]) -> set[int]:
    positions = {
        index
        for index, character in enumerate(content.characters)
        if character in "0123456789零一二三四五六七八九十百千万亿两"
    }
    for match in re.finditer("[A-Z][a-z]+", content.raw):
        positions.update(
            (
                index
                for index, (start, end) in enumerate(zip(content.starts, content.ends, strict=True))
                if start < match.end() and end > match.start()
            )
        )
    haystack = "".join(content.characters)
    for hotword in hotwords:
        needle = normalized(hotword)
        start = 0
        while needle and (found := haystack.find(needle, start)) >= 0:
            positions.update(range(found, found + len(needle)))
            start = found + 1
    return positions


def _touches_protected(start: int, end: int, positions: set[int]) -> bool:
    if start == end:
        return start in positions or start - 1 in positions
    return any(index in positions for index in range(start, end))


def _edits(primary: _Content, revision: str, hotwords: tuple[str, ...] = ()) -> list[_Edit]:
    revised = _content(revision)
    revised_protected = _protected_positions(revised, hotwords)
    return [
        _Edit(
            start=start,
            end=end,
            replacement=revised.characters[replacement_start:replacement_end],
            raw_replacement=revised.slice(replacement_start, replacement_end),
            replacement_protected=_touches_protected(
                replacement_start, replacement_end, revised_protected
            ),
        )
        for tag, start, end, replacement_start, replacement_end in difflib.SequenceMatcher(
            None, primary.characters, revised.characters, autojunk=False
        ).get_opcodes()
        if tag != "equal"
    ]


def choose(
    primary: str,
    model: str,
    candidates: dict[str, str],
    reviews: dict[str, str],
    families: dict[str, str],
    *,
    hotwords: tuple[str, ...],
    protected: bool,
) -> tuple[str, str]:
    revised = reviews.get(model, "")
    if protected or not revised or normalized(revised) == normalized(primary):
        return (primary, "primary")
    content = _content(primary)
    protected_positions = _protected_positions(content, hotwords)
    full_support = [
        source
        for source, text in reviews.items()
        if families[source] != families[model] and normalized(text) == normalized(revised)
    ]
    if full_support and (not protected_positions):
        return (revised, f"review_supported_by:{','.join(sorted(full_support))}")
    if model != "qwen3-asr-1.7b":
        return (primary, "unresolved")
    proposed = _edits(content, revised, hotwords)
    independent = {
        source: {edit.signature for edit in _edits(content, text)}
        for source, text in (candidates | reviews).items()
        if families[source] != families[model]
    }
    accepted = [
        edit
        for edit in proposed
        if edit.start >= 4
        and len(content.characters) - edit.end >= 4
        and (not _touches_protected(edit.start, edit.end, protected_positions))
        and (not edit.replacement_protected)
        and (
            len(
                {
                    families[source]
                    for source, edits in independent.items()
                    if edit.signature in edits
                }
            )
            >= 2
        )
    ]
    if not accepted:
        return (primary, "unresolved")
    result = content.raw
    supporters: set[str] = set()
    for edit in reversed(accepted):
        start, end = content.range(edit.start, edit.end)
        result = result[:start] + edit.raw_replacement + result[end:]
        supporters.update(
            (source for source, edits in independent.items() if edit.signature in edits)
        )
    decision = (
        "local_consensus_supported_by"
        if len(accepted) == len(proposed)
        else "local_consensus_partially_supported_by"
    )
    return (result, f"{decision}:{','.join(sorted(supporters))}")


async def transcribe(
    inference: Inference, audio: Path, duration: int, options: Options
) -> Transcript:
    result = Transcript(recipe="meeting/qwen_nemotron")

    async def recognize_audio() -> tuple[list[Segment], list[Span], list[Span]]:
        path = audio
        detection = asyncio.create_task(
            inference.call("firered-vad", InferenceRequest(audio=str(path)), step="vad")
        )
        diarization = asyncio.create_task(
            inference.call(
                "nemotron-diarization",
                InferenceRequest(audio=str(path), num_speakers=options.num_speakers),
                step="diarization",
            )
        )
        activity = (await detection).spans
        chunks = windows(activity, duration, ChunkConfig(target_seconds=24, padding_ms=300))

        async def window(window: Window) -> list[Segment]:
            clip = inference.work / f"clip-{window.start_ms}-{window.end_ms}.wav"
            async with inference.models.cpu:
                await asyncio.to_thread(cut, path, clip, window.start_ms, window.end_ms)

            async def recognize(model: str, source: Path, step: str) -> str:
                response = await inference.call(
                    model,
                    InferenceRequest(
                        audio=str(source),
                        hotwords=options.hotwords,
                        mode="meeting",
                        language=options.language,
                    ),
                    step=step,
                )
                return plain(response.text)

            names = ("qwen3-asr-1.7b", "firered-llm", "sensevoice", "paraformer")
            values = await asyncio.gather(*(recognize(model, clip, "recognize") for model in names))
            candidates = dict(zip(names, values, strict=True))
            speakers = rename_speakers((await diarization).spans)
            original = candidates["qwen3-asr-1.7b"]
            reviews: dict[str, str] = {}
            protected = len(owners(window.core_start_ms, window.core_end_ms, speakers)) > 1
            if not protected and len({normalized(text) for text in values}) > 1:
                expanded = Window(
                    start_ms=max(0, window.start_ms - 2000),
                    end_ms=min(duration, window.end_ms + 2000),
                    core_start_ms=window.core_start_ms,
                    core_end_ms=window.core_end_ms,
                )
                if expanded.end_ms - expanded.start_ms > 30000:
                    expanded.end_ms = expanded.start_ms + 30000
                expanded_clip = inference.work / f"review-{expanded.start_ms}-{expanded.end_ms}.wav"
                async with inference.models.cpu:
                    await asyncio.to_thread(
                        cut, path, expanded_clip, expanded.start_ms, expanded.end_ms
                    )

                async def review(model: str) -> tuple[str, str]:
                    text = await recognize(model, expanded_clip, "review")
                    aligned = await inference.call(
                        "qwen3-aligner",
                        InferenceRequest(audio=str(expanded_clip), text=text),
                        step="review.align",
                    )
                    tokens = align_text(
                        text,
                        aligned.tokens,
                        offset=expanded.start_ms,
                        limit=expanded.end_ms - expanded.start_ms,
                    )
                    return (
                        model,
                        "".join(
                            token.text
                            for token in tokens
                            if token.start_ms is not None
                            and token.end_ms is not None
                            and (
                                window.start_ms
                                <= (token.start_ms + token.end_ms) / 2
                                < window.end_ms
                            )
                        ),
                    )

                moss = asyncio.create_task(recognize("moss-audio", expanded_clip, "review"))
                reviews = dict(
                    await asyncio.gather(
                        *(
                            review(model)
                            for model in ("qwen3-asr-1.7b", "firered-llm", "whisper-large-v3")
                        )
                    )
                )
                moss_text = await moss
                if len({normalized(value) for value in reviews.values()}) > 1:
                    moss_alignment = await inference.call(
                        "qwen3-aligner",
                        InferenceRequest(audio=str(expanded_clip), text=moss_text),
                        step="review.align",
                    )
                    moss_tokens = align_text(
                        moss_text,
                        moss_alignment.tokens,
                        offset=expanded.start_ms,
                        limit=expanded.end_ms - expanded.start_ms,
                    )
                    reviews["moss-audio"] = "".join(
                        token.text
                        for token in moss_tokens
                        if token.start_ms is not None
                        and token.end_ms is not None
                        and window.start_ms <= (token.start_ms + token.end_ms) / 2 < window.end_ms
                    )
            text, decision = choose(
                original,
                "qwen3-asr-1.7b",
                candidates,
                reviews,
                {
                    "qwen3-asr-1.7b": "qwen",
                    "firered-llm": "firered",
                    "whisper-large-v3": "whisper",
                    "sensevoice": "sensevoice",
                    "paraformer": "paraformer",
                    "moss-audio": "moss-audio",
                },
                hotwords=tuple(options.hotwords),
                protected=protected,
            )
            if not normalized(text):
                return []
            source = punctuation_input(text)
            punctuated = await inference.call(
                "firered-punc", InferenceRequest(text=source), step="punctuate"
            )
            if punctuation_content(punctuated.text) != punctuation_content(source):
                raise ValueError(
                    f"punctuation changed transcript content: {source!r} -> {punctuated.text!r}"
                )
            text = punctuated.text
            aligned = await inference.call(
                "qwen3-aligner",
                InferenceRequest(audio=str(clip), text=text),
                step="align",
            )
            tokens = align_text(
                text, aligned.tokens, offset=window.start_ms, limit=window.end_ms - window.start_ms
            )
            tokens = [
                token
                for token in tokens
                if token.start_ms is None
                or token.end_ms is None
                or window.core_start_ms <= (token.start_ms + token.end_ms) / 2 < window.core_end_ms
            ]
            segment = Segment(
                start_ms=window.core_start_ms,
                end_ms=window.core_end_ms,
                text="".join(token.text for token in tokens),
                tokens=tokens,
                candidates=candidates,
                reviews=reviews,
                decision=decision,
                flags=punctuated.warnings
                + (["alignment_failed"] if any(t.start_ms is None for t in tokens) else []),
            )
            parts = utterances(segment, speakers)
            return parts

        batches = await asyncio.gather(*(window(chunk) for chunk in chunks))
        return (
            [part for batch in batches for part in batch],
            rename_speakers((await diarization).spans),
            activity,
        )

    segments, speakers, activity = await recognize_audio()
    result.segments = segments
    result.segments.sort(key=lambda segment: (segment.start_ms, segment.channel or 0))
    result.speakers = speakers
    result.activity = union(activity)
    return result
