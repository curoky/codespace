# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML==6.0.3", "rapidfuzz==3.14.6"]
# ///
import argparse
import functools
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parent
EXPECTED_RECIPES = (
    "01-qwen-fusion",
    "02-firered-fusion",
    "03-moss-td",
    "04-vibevoice",
    "05-qwen-nemotron",
)
ANNOTATION = re.compile(r"\[(?:LAUGHTER|NOISE|VOCALIZED-NOISE|\*|\+)\]", re.IGNORECASE)
FOOTNOTE_MARKERS = str.maketrans("", "", "⑴⑵⑶⑷⑸⑹⑺⑻⑼⑽")


@dataclass(frozen=True)
class Span:
    start_ms: int
    end_ms: int
    speaker: str
    text: str


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(text: str) -> str:
    text = ANNOTATION.sub("", text.translate(FOOTNOTE_MARKERS))
    text = unicodedata.normalize("NFKC", text).casefold()
    return "".join(character for character in text if unicodedata.category(character)[0] in "LN")


def edit_counts(reference: str, hypothesis: str) -> dict[str, int | float]:
    operations = Levenshtein.editops(reference, hypothesis)
    substitutions = sum(operation.tag == "replace" for operation in operations)
    deletions = sum(operation.tag == "delete" for operation in operations)
    insertions = sum(operation.tag == "insert" for operation in operations)
    distance = substitutions + deletions + insertions
    if not reference:
        raise ValueError("normalized reference is empty")
    return {
        "reference_characters": len(reference),
        "hypothesis_characters": len(hypothesis),
        "substitutions": substitutions,
        "deletions": deletions,
        "insertions": insertions,
        "cer": distance / len(reference),
        "character_accuracy": max(0.0, 1 - distance / len(reference)),
    }


def parse_magicdata(path: Path) -> list[Span]:
    spans = []
    for line_number, line in enumerate(path.read_text().splitlines(), 1):
        fields = line.split("\t", 3)
        if len(fields) != 4:
            raise ValueError(f"{path}:{line_number}: expected four tab-separated fields")
        times, speaker, _language, text = fields
        match = re.fullmatch(r"\[([0-9.]+),([0-9.]+)\]", times)
        if match is None:
            raise ValueError(f"{path}:{line_number}: invalid time range")
        if speaker == "G00000000":
            continue
        spans.append(
            Span(
                round(float(match.group(1)) * 1000),
                round(float(match.group(2)) * 1000),
                speaker,
                text,
            )
        )
    return spans


def parse_textgrid(path: Path, end_ms: int) -> list[Span]:
    spans = []
    speaker = None
    start = None
    end = None
    in_interval = False
    for line_number, raw_line in enumerate(path.read_text().splitlines(), 1):
        line = raw_line.strip()
        if line.startswith("name = "):
            speaker = line.removeprefix("name = ").strip('"')
        elif line.startswith("intervals ["):
            in_interval = True
            start = None
            end = None
        elif in_interval and line.startswith("xmin = "):
            start = round(float(line.removeprefix("xmin = ")) * 1000)
        elif in_interval and line.startswith("xmax = "):
            end = round(float(line.removeprefix("xmax = ")) * 1000)
        elif in_interval and line.startswith("text = "):
            if speaker is None or start is None or end is None:
                raise ValueError(f"{path}:{line_number}: incomplete TextGrid interval")
            text = line.removeprefix("text = ").strip('"').replace('""', '"')
            if text and start < end_ms:
                spans.append(Span(start, min(end, end_ms), speaker, text))
            in_interval = False
    return spans


def parse_source_text(path: Path, reference: dict[str, object], duration_ms: int) -> list[Span]:
    text = path.read_text()
    start_marker = str(reference["start_marker"])
    end_marker = str(reference["end_marker"])
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise ValueError(f"cannot find source-text markers in {path}")
    end += len(end_marker)
    return [
        Span(
            int(reference.get("audio_start_ms", 0)),
            int(reference.get("audio_end_ms", duration_ms)),
            "R01",
            text[start:end],
        )
    ]


def reference_spans(fixture: dict[str, object]) -> list[Span]:
    reference = fixture["reference"]
    audio = fixture["audio"]
    if not isinstance(reference, dict) or not isinstance(audio, dict):
        raise ValueError(f"invalid manifest entry for {fixture['id']}")
    path = ROOT / str(reference["path"])
    expected = str(reference["sha256"])
    actual = sha256(path)
    if actual != expected:
        raise ValueError(f"reference sha256 mismatch for {fixture['id']}: {actual}")
    match reference["format"]:
        case "magicdata_tsv":
            return parse_magicdata(path)
        case "textgrid":
            return parse_textgrid(path, int(reference["end_ms"]))
        case "source_text":
            return parse_source_text(path, reference, int(audio["duration_ms"]))
        case other:
            raise ValueError(f"unsupported reference format: {other}")


def hypothesis_spans(document: dict[str, object], start_ms: int, end_ms: int) -> list[Span]:
    spans = []
    for segment in document["segments"]:
        if not isinstance(segment, dict):
            raise ValueError("invalid result segment")
        segment_start = int(segment["start_ms"])
        segment_end = int(segment["end_ms"])
        midpoint = (segment_start + segment_end) // 2
        if midpoint < start_ms or midpoint > end_ms:
            continue
        speakers = segment.get("speakers") or ["unknown"]
        spans.append(Span(segment_start, segment_end, str(speakers[0]), str(segment["text"])))
    return spans


def speaker_spans(document: dict[str, object], start_ms: int, end_ms: int) -> list[Span]:
    spans = []
    for item in document["speakers"]:
        if not isinstance(item, dict):
            raise ValueError("invalid speaker activity")
        start = max(start_ms, int(item["start_ms"]))
        end = min(end_ms, int(item["end_ms"]))
        if start < end:
            spans.append(Span(start, end, str(item["speaker"]), ""))
    return spans


def token_text_by_speaker(
    document: dict[str, object], start_ms: int, end_ms: int
) -> dict[str, str]:
    values: dict[str, list[str]] = defaultdict(list)
    for segment in document["segments"]:
        if not isinstance(segment, dict):
            raise ValueError("invalid result segment")
        tokens = segment.get("tokens") or []
        segment_start = int(segment["start_ms"])
        segment_end = int(segment["end_ms"])
        segment_speakers = segment.get("speakers") or ["unknown"]
        if not tokens:
            if start_ms <= (segment_start + segment_end) // 2 <= end_ms:
                values[str(segment_speakers[0])].append(str(segment["text"]))
            continue
        for token in tokens:
            if token["start_ms"] is None or token["end_ms"] is None:
                if start_ms <= (segment_start + segment_end) // 2 <= end_ms:
                    values[str(segment_speakers[0])].append(str(token["text"]))
                continue
            token_start = int(token["start_ms"])
            token_end = int(token["end_ms"])
            if not start_ms <= (token_start + token_end) // 2 <= end_ms:
                continue
            speakers = token.get("speakers") or ["unknown"]
            values[str(speakers[0])].append(str(token["text"]))
    return {speaker: normalize("".join(parts)) for speaker, parts in values.items()}


def concatenate_by_speaker(spans: Iterable[Span]) -> dict[str, str]:
    values: dict[str, list[str]] = defaultdict(list)
    for span in sorted(spans, key=lambda value: (value.start_ms, value.end_ms)):
        values[span.speaker].append(span.text)
    return {speaker: normalize("".join(parts)) for speaker, parts in values.items()}


def permutation_cer(reference: dict[str, str], hypothesis: dict[str, str]) -> float:
    references = list(reference.values())
    hypotheses = list(hypothesis.values())
    total = sum(map(len, references))
    if not total:
        raise ValueError("speaker-attributed reference is empty")

    @functools.cache
    def assign(index: int, used: int) -> int:
        if index == len(references):
            return sum(
                len(text) for position, text in enumerate(hypotheses) if not used & (1 << position)
            )
        best = len(references[index]) + assign(index + 1, used)
        for position, text in enumerate(hypotheses):
            if used & (1 << position):
                continue
            distance = Levenshtein.distance(references[index], text)
            best = min(best, distance + assign(index + 1, used | (1 << position)))
        return best

    return assign(0, 0) / total


def best_speaker_mapping(reference: list[Span], hypothesis: list[Span]) -> dict[str, str]:
    reference_speakers = sorted({span.speaker for span in reference})
    hypothesis_speakers = sorted({span.speaker for span in hypothesis})
    overlap = {
        (ref, hyp): sum(
            max(0, min(left.end_ms, right.end_ms) - max(left.start_ms, right.start_ms))
            for left in reference
            if left.speaker == ref
            for right in hypothesis
            if right.speaker == hyp
        )
        for ref in reference_speakers
        for hyp in hypothesis_speakers
    }

    @functools.cache
    def assign(index: int, used: int) -> tuple[int, tuple[tuple[str, str], ...]]:
        if index == len(reference_speakers):
            return 0, ()
        score, pairs = assign(index + 1, used)
        ref = reference_speakers[index]
        for position, hyp in enumerate(hypothesis_speakers):
            if used & (1 << position):
                continue
            tail_score, tail_pairs = assign(index + 1, used | (1 << position))
            candidate = overlap[(ref, hyp)] + tail_score
            if candidate > score:
                score = candidate
                pairs = ((hyp, ref), *tail_pairs)
        return score, pairs

    return dict(assign(0, 0)[1])


def diarization_error_rate(reference: list[Span], hypothesis: list[Span]) -> float:
    mapping = best_speaker_mapping(reference, hypothesis)
    events: dict[int, list[tuple[str, str, bool]]] = defaultdict(list)
    for kind, spans in (("reference", reference), ("hypothesis", hypothesis)):
        for span in spans:
            events[span.start_ms].append((kind, span.speaker, True))
            events[span.end_ms].append((kind, span.speaker, False))

    active_reference: set[str] = set()
    active_hypothesis: set[str] = set()
    previous = min(events)
    reference_time = 0
    error_time = 0
    for timestamp in sorted(events):
        duration = timestamp - previous
        if duration:
            reference_count = len(active_reference)
            hypothesis_count = len(active_hypothesis)
            correct = sum(mapping.get(speaker) in active_reference for speaker in active_hypothesis)
            misses = max(0, reference_count - hypothesis_count)
            false_alarms = max(0, hypothesis_count - reference_count)
            confusion = min(reference_count, hypothesis_count) - correct
            reference_time += reference_count * duration
            error_time += (misses + false_alarms + confusion) * duration
        for kind, speaker, added in events[timestamp]:
            active = active_reference if kind == "reference" else active_hypothesis
            if added:
                active.add(speaker)
            else:
                active.discard(speaker)
        previous = timestamp
    if not reference_time:
        raise ValueError("diarization reference is empty")
    return error_time / reference_time


def evaluate_fixture(fixture: dict[str, object]) -> list[dict[str, object]]:
    reference = reference_spans(fixture)
    start_ms = min(span.start_ms for span in reference)
    end_ms = max(span.end_ms for span in reference)
    ordered_reference = sorted(reference, key=lambda value: value.start_ms)
    reference_text = normalize("".join(span.text for span in ordered_reference))
    reference_by_speaker = concatenate_by_speaker(reference)
    audio = fixture["audio"]
    reference_config = fixture["reference"]
    if not isinstance(audio, dict) or not isinstance(reference_config, dict):
        raise ValueError(f"invalid manifest entry for {fixture['id']}")
    has_gold_timing = reference_config["quality"] == "gold"
    result_directory = ROOT / str(fixture["category"]) / "results" / Path(str(audio["path"])).name
    rows = []
    for recipe in EXPECTED_RECIPES:
        path = result_directory / f"{recipe}.json"
        document = json.loads(path.read_text())
        if document.get("status") != "completed":
            rows.append(
                {
                    "fixture": fixture["id"],
                    "category": fixture["category"],
                    "recipe": recipe,
                    "reference_quality": reference_config["quality"],
                    "status": "failed",
                    "error": document.get("error"),
                    "reference_characters": len(reference_text),
                    "hypothesis_characters": None,
                    "substitutions": None,
                    "deletions": None,
                    "insertions": None,
                    "cer": None,
                    "character_accuracy": None,
                    "speaker_attributed_cer": None,
                    "diarization_error_rate": None,
                }
            )
            continue
        hypothesis = hypothesis_spans(document, start_ms, end_ms)
        hypothesis_text = normalize("".join(span.text for span in hypothesis))
        counts = edit_counts(reference_text, hypothesis_text)
        hypothesis_by_speaker = token_text_by_speaker(document, start_ms, end_ms)
        activity = speaker_spans(document, start_ms, end_ms)
        counts.update(
            {
                "fixture": fixture["id"],
                "category": fixture["category"],
                "recipe": recipe,
                "reference_quality": reference_config["quality"],
                "status": "completed",
                "error": None,
                "speaker_attributed_cer": (
                    permutation_cer(reference_by_speaker, hypothesis_by_speaker)
                    if has_gold_timing
                    else None
                ),
                "diarization_error_rate": (
                    diarization_error_rate(reference, activity) if has_gold_timing else None
                ),
            }
        )
        rows.append(counts)
    return rows


def aggregate(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["category"]), str(row["recipe"]))].append(row)
        groups[("all", str(row["recipe"]))].append(row)
    output = []
    for (category, recipe), members in sorted(groups.items()):
        completed = [row for row in members if row["status"] == "completed"]
        speaker_attributed = [
            float(row["speaker_attributed_cer"])
            for row in completed
            if row["speaker_attributed_cer"] is not None
        ]
        diarization = [
            float(row["diarization_error_rate"])
            for row in completed
            if row["diarization_error_rate"] is not None
        ]
        output.append(
            {
                "category": category,
                "recipe": recipe,
                "fixtures": len(members),
                "completed": len(completed),
                "failed": len(members) - len(completed),
                "macro_cer": (
                    sum(float(row["cer"]) for row in completed) / len(completed)
                    if completed
                    else None
                ),
                "macro_speaker_attributed_cer": (
                    sum(speaker_attributed) / len(speaker_attributed)
                    if speaker_attributed
                    else None
                ),
                "macro_diarization_error_rate": (
                    sum(diarization) / len(diarization) if diarization else None
                ),
            }
        )
    return output


def markdown(rows: list[dict[str, object]]) -> str:
    lines = [
        "| Fixture | Recipe | CER | SA-CER | DER |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        if row["status"] != "completed":
            lines.append(f"| {row['fixture']} | {row['recipe']} | failed | — | — |")
            continue
        attributed = row["speaker_attributed_cer"]
        diarization = row["diarization_error_rate"]
        attributed_text = f"{float(attributed):.2%}" if attributed is not None else "—"
        diarization_text = f"{float(diarization):.2%}" if diarization is not None else "—"
        lines.append(
            f"| {row['fixture']} | {row['recipe']} | {float(row['cer']):.2%} | "
            f"{attributed_text} | {diarization_text} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "metrics.json")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()
    manifest = yaml.safe_load((ROOT / "manifest.yaml").read_text())
    rows = [row for fixture in manifest["fixtures"] for row in evaluate_fixture(fixture)]
    payload = {"schema_version": 1, "results": rows, "aggregates": aggregate(rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(markdown(rows) if args.markdown else args.output)


if __name__ == "__main__":
    main()
