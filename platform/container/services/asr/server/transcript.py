import difflib
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

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
            return boundary, boundary
        return self.starts[start], self.ends[end - 1]


@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: tuple[str, ...]
    raw_replacement: str
    replacement_protected: bool

    @property
    def signature(self) -> tuple[int, int, tuple[str, ...]]:
        return self.start, self.end, self.replacement


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
    for match in re.finditer(r"[A-Z][a-z]+", content.raw):
        positions.update(
            index
            for index, (start, end) in enumerate(zip(content.starts, content.ends, strict=True))
            if start < match.end() and end > match.start()
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
        return primary, "primary"
    content = _content(primary)
    protected_positions = _protected_positions(content, hotwords)
    full_support = [
        source
        for source, text in reviews.items()
        if families[source] != families[model] and normalized(text) == normalized(revised)
    ]
    if full_support and not protected_positions:
        return revised, f"review_supported_by:{','.join(sorted(full_support))}"
    if model != "qwen3-asr-1.7b":
        return primary, "unresolved"

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
        and not _touches_protected(edit.start, edit.end, protected_positions)
        and not edit.replacement_protected
        and len(
            {families[source] for source, edits in independent.items() if edit.signature in edits}
        )
        >= 2
    ]
    if not accepted:
        return primary, "unresolved"

    result = content.raw
    supporters: set[str] = set()
    for edit in reversed(accepted):
        start, end = content.range(edit.start, edit.end)
        result = result[:start] + edit.raw_replacement + result[end:]
        supporters.update(
            source for source, edits in independent.items() if edit.signature in edits
        )
    decision = (
        "local_consensus_supported_by"
        if len(accepted) == len(proposed)
        else "local_consensus_partially_supported_by"
    )
    return result, f"{decision}:{','.join(sorted(supporters))}"
