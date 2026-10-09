import re
import unicodedata
from collections import defaultdict

from pydantic import Field

from protocol import Record, Span, Token


class Segment(Record):
    channel: int | None = None
    start_ms: int
    end_ms: int
    text: str
    speakers: list[str] = Field(default_factory=list)
    tokens: list[Token] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    candidates: dict[str, str] = Field(default_factory=dict)
    reviews: dict[str, str] = Field(default_factory=dict)
    decision: str = "primary"


class Transcript(Record):
    recipe: str
    status: str = "completed"
    error: str | None = None
    segments: list[Segment] = Field(default_factory=list)
    activity: list[Span] = Field(default_factory=list)
    speakers: list[Span] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def plain(text: str) -> str:
    return re.sub(r"<\|[^|]+\|>", "", text)


def normalized(text: str) -> str:
    return "".join(
        ch.lower()
        for ch in plain(text)
        if not ch.isspace() and not unicodedata.category(ch).startswith("P")
    )


def punctuation_content(text: str) -> str:
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith("P"))


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
        speaker for speaker, score in scores.items() if score >= max(1, (end - start) * 0.25)
    )


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
    result: dict[str, str | None] = {}
    for speaker in {s.speaker for s in local if s.speaker}:
        ranked = sorted(votes[speaker].items(), key=lambda item: item[1], reverse=True)
        result[speaker] = (
            ranked[0][0]
            if ranked
            and ranked[0][1] >= 500
            and (len(ranked) == 1 or ranked[0][1] >= 2 * ranked[1][1])
            else None
        )
    return result


def align_text(text: str, tokens: list[Token], *, offset: int, limit: int) -> list[Token]:
    indices = [
        i
        for i, char in enumerate(text)
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    ]
    if not tokens or normalized("".join(t.text for t in tokens)) != normalized(text):
        return [Token(text=text)] if text else []
    result = []
    consumed = 0
    previous = 0
    for token in tokens:
        consumed += len(normalized(token.text))
        boundary = indices[consumed] if consumed < len(indices) else len(text)
        start, end = token.start_ms, token.end_ms
        if start is not None and end is not None and 0 <= start <= end <= limit:
            start, end = start + offset, end + offset
        else:
            start, end = None, None
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
        current.end_ms = token.end_ms if token.end_ms is not None else segment.end_ms
        if len(token.speakers) > 1 and "overlap" not in current.flags:
            current.flags.append("overlap")
        if not token.speakers and "speaker_unknown" not in current.flags:
            current.flags.append("speaker_unknown")
    return result or [segment]


def choose(
    primary: str, model: str, reviews: dict[str, str], families: dict[str, str], *, protected: bool
) -> tuple[str, str]:
    revised = reviews.get(model, "")
    if protected or not revised or normalized(revised) == normalized(primary):
        return primary, "primary"
    support = [
        source
        for source, text in reviews.items()
        if families[source] != families[model] and normalized(text) == normalized(revised)
    ]
    if not support:
        return primary, "unresolved"
    return revised, f"expanded_primary_supported_by:{','.join(sorted(support))}"
