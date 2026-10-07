import itertools
from importlib import import_module

from protocol import Span, Token
from server.audio import union, windows
from server.config import ChunkConfig
from server.transcript import align_text, choose, mapped_identity, normalized, owners

parse_joint = import_module("models.moss-td.client").parse


def test_normalization_keeps_negation_numbers_units_and_repetition() -> None:
    assert normalized("<|zh|><|NEUTRAL|>不，不是 15 万。") == "不不是15万"
    assert normalized("是15万") != normalized("不是50万")


def test_consensus_requires_changed_primary_and_an_independent_family() -> None:
    families = {"a": "qwen", "copy": "qwen", "b": "firered"}
    assert (
        choose("旧句", "a", {"a": "新句", "copy": "新句"}, families, protected=False)[0] == "旧句"
    )
    assert choose("旧句", "a", {"a": "新句", "b": "新句"}, families, protected=False)[0] == "新句"
    assert choose("15万", "a", {"a": "50万", "b": "50万"}, families, protected=True)[0] == "15万"


def test_vad_union_covers_speaker_activity_and_bounded_windows() -> None:
    activity = union([Span(start_ms=100, end_ms=26000), Span(start_ms=25000, end_ms=60000)])
    clips = windows(activity, 61000, ChunkConfig())
    assert clips[0].core_start_ms == 0
    assert clips[-1].core_end_ms == 60300
    assert all(clip.end_ms - clip.start_ms <= 30000 for clip in clips)
    assert all(a.core_end_ms == b.core_start_ms for a, b in itertools.pairwise(clips))
    assert clips[0].end_ms > clips[1].start_ms


def test_alignment_preserves_text_and_does_not_invent_invalid_times() -> None:
    tokens = align_text(
        "你好， hello!",
        [
            Token(text="你", start_ms=100, end_ms=200),
            Token(text="好", start_ms=200, end_ms=300),
            Token(text="hello", start_ms=350, end_ms=500),
        ],
        offset=9000,
        limit=1000,
    )
    assert "".join(t.text for t in tokens) == "你好， hello!"
    assert tokens[0].start_ms == 9100
    failed = align_text(
        "没有说过的话", [Token(text="不匹配", start_ms=0, end_ms=5)], offset=0, limit=1000
    )
    assert failed == [Token(text="没有说过的话")]


def test_overlap_keeps_candidates_without_duplicating_text() -> None:
    speakers = [
        Span(start_ms=0, end_ms=1000, speaker="S01"),
        Span(start_ms=500, end_ms=1500, speaker="S02"),
    ]
    assert owners(600, 900, speakers) == ["S01", "S02"]
    assert owners(None, None, speakers) == []


def test_local_speaker_names_are_mapped_by_evidence() -> None:
    reference = [
        Span(start_ms=0, end_ms=3000, speaker="S01"),
        Span(start_ms=4000, end_ms=7000, speaker="S02"),
    ]
    assert mapped_identity([Span(start_ms=4200, end_ms=6800, speaker="S01")], reference) == {
        "S01": "S02"
    }


def test_joint_transcript_parsing_preserves_overlap() -> None:
    result = parse_joint("[0.2][S01]你好[1.5][1.0][S02]嗯[2.0]")
    assert result[0].end_ms > result[1].start_ms
    assert [s.text for s in result] == ["你好", "嗯"]
