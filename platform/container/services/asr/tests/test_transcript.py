import itertools
from importlib import import_module

from protocol import Span, Token
from server.audio import union, windows
from server.config import ChunkConfig
from server.transcript import (
    Segment,
    align_text,
    choose,
    mapped_identity,
    normalized,
    owners,
    punctuation_input,
    utterances,
)

parse_joint = import_module("models.moss-td.client").parse


def test_normalization_keeps_negation_numbers_units_and_repetition() -> None:
    assert normalized("<|zh|><|NEUTRAL|>不，不是 15 万。") == "不不是15万"
    assert normalized("是15万") != normalized("不是50万")


def test_consensus_uses_full_review_support_for_every_primary() -> None:
    families = {"a": "qwen", "copy": "qwen", "b": "firered"}
    assert (
        choose(
            "旧句",
            "a",
            {},
            {"a": "新句", "copy": "新句"},
            families,
            hotwords=(),
            protected=False,
        )[0]
        == "旧句"
    )
    assert (
        choose(
            "旧句",
            "a",
            {},
            {"a": "新句", "b": "新句"},
            families,
            hotwords=(),
            protected=False,
        )[0]
        == "新句"
    )
    assert (
        choose(
            "15万",
            "a",
            {},
            {"a": "50万", "b": "50万"},
            families,
            hotwords=(),
            protected=True,
        )[0]
        == "15万"
    )


def test_qwen_consensus_accepts_supported_local_edits_with_stable_context() -> None:
    families = {
        "qwen3-asr-1.7b": "qwen",
        "firered-llm": "firered",
        "whisper-large-v3": "whisper",
    }
    text, decision = choose(
        "甲乙丙丁这里是错字后面还有四字",
        "qwen3-asr-1.7b",
        {
            "firered-llm": "甲乙丙丁这里是正字后面另有四字",
            "whisper-large-v3": "甲乙丙丁这里是正字后面仍有四字",
        },
        {"qwen3-asr-1.7b": "甲乙丙丁这里是正字后面还有四字"},
        families,
        hotwords=(),
        protected=False,
    )
    assert text == "甲乙丙丁这里是正字后面还有四字"
    assert decision == "local_consensus_supported_by:firered-llm,whisper-large-v3"


def test_local_consensus_rejects_boundary_edits_and_keeps_firered_conservative() -> None:
    families = {
        "qwen3-asr-1.7b": "qwen",
        "firered-llm": "firered",
        "whisper-large-v3": "whisper",
    }
    boundary = {
        "qwen3-asr-1.7b": "正乙丙丁戊己庚辛壬癸",
        "firered-llm": "正乙丙丁戊己庚辛另外",
    }
    assert choose(
        "错乙丙丁戊己庚辛壬癸",
        "qwen3-asr-1.7b",
        boundary,
        boundary,
        families,
        hotwords=(),
        protected=False,
    ) == ("错乙丙丁戊己庚辛壬癸", "unresolved")
    assert choose(
        "甲乙丙丁这里是错字后面还有四字",
        "firered-llm",
        {},
        {
            "firered-llm": "甲乙丙丁这里是正字后面还有四字",
            "qwen3-asr-1.7b": "甲乙丙丁这里是正字后面另有四字",
        },
        families,
        hotwords=(),
        protected=False,
    ) == ("甲乙丙丁这里是错字后面还有四字", "unresolved")


def test_local_consensus_protects_only_the_sensitive_edit_spans() -> None:
    families = {
        "qwen3-asr-1.7b": "qwen",
        "firered-llm": "firered",
        "whisper-large-v3": "whisper",
    }
    primary = "甲乙丙丁十五万量子引擎这里是错字后面还有四字"
    revised = "甲乙丙丁五十万量子引晴这里是正字后面还有四字"
    supporters = {
        "firered-llm": "甲乙丙丁五十万量子引晴这里是正字后面另有四字",
        "whisper-large-v3": "甲乙丙丁五十万量子引晴这里是正字后面仍有四字",
    }
    text, decision = choose(
        primary,
        "qwen3-asr-1.7b",
        supporters,
        {"qwen3-asr-1.7b": revised},
        families,
        hotwords=("量子引擎",),
        protected=False,
    )
    assert text == "甲乙丙丁十五万量子引擎这里是正字后面还有四字"
    assert decision == "local_consensus_partially_supported_by:firered-llm,whisper-large-v3"


def test_punctuation_input_has_one_sentence_punctuation_owner() -> None:
    assert (
        punctuation_input(
            "大病，，是归故乡\uff1f\uff1f3.14、12,000《狂人日记》。她说：“你好\uff01”"
        )
        == "大病是归故乡3.1412,000狂人日记她说你好"
    )


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
    assert owners(600, 600, speakers) == ["S01", "S02"]
    assert owners(1000, 1000, speakers) == ["S02"]
    assert owners(None, None, speakers) == []


def test_zero_duration_token_uses_point_speaker_and_stays_in_utterance() -> None:
    segment = Segment(
        start_ms=600,
        end_ms=800,
        text="我不",
        tokens=[
            Token(text="我", start_ms=600, end_ms=600),
            Token(text="不", start_ms=600, end_ms=800),
        ],
    )

    result = utterances(segment, [Span(start_ms=0, end_ms=1000, speaker="S01")])

    assert len(result) == 1
    assert result[0].text == "我不"
    assert result[0].speakers == ["S01"]
    assert result[0].tokens[0].speakers == ["S01"]
    assert "speaker_unknown" not in result[0].flags


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
