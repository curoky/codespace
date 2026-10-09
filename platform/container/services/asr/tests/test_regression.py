import hashlib
import importlib.util
import json
import sys
import wave
from pathlib import Path
from types import ModuleType

import yaml

ASR_ROOT = Path(__file__).parents[1]
REGRESSION_ROOT = ASR_ROOT / "regression"


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


evaluate = load_module("asr_regression_evaluate", REGRESSION_ROOT / "evaluate.py")
prepare = load_module("asr_regression_prepare", REGRESSION_ROOT / "prepare.py")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_regression_manifest_has_three_complete_fixtures_per_category() -> None:
    manifest = yaml.safe_load((REGRESSION_ROOT / "manifest.yaml").read_text())

    assert manifest["schema_version"] == 1
    assert {fixture["category"] for fixture in manifest["fixtures"]} == {
        "conversation",
        "meeting",
        "narration",
    }
    for category in ("conversation", "meeting", "narration"):
        assert sum(fixture["category"] == category for fixture in manifest["fixtures"]) == 3

    fixture_ids = set()
    audio_paths = set()
    for fixture in manifest["fixtures"]:
        assert fixture["id"] not in fixture_ids
        fixture_ids.add(fixture["id"])
        assert fixture["source"] in manifest["sources"]
        audio = fixture["audio"]
        assert audio["path"].startswith(f"{fixture['category']}/audio/")
        assert audio["path"] not in audio_paths
        audio_paths.add(audio["path"])
        assert len(audio["sha256"]) == 64
        assert audio["size_bytes"] > 0
        assert audio["duration_ms"] >= 1_200_000
        result_directory = (
            REGRESSION_ROOT / fixture["category"] / "results" / Path(audio["path"]).name
        )
        assert (result_directory / "evidence.json").is_file()
        assert (result_directory / "trace.json").is_file()
        for recipe in evaluate.EXPECTED_RECIPES:
            result = json.loads((result_directory / f"{recipe}.json").read_text())
            assert result["status"] in {"completed", "failed"}
        reference = fixture["reference"]
        reference_path = REGRESSION_ROOT / reference["path"]
        assert reference_path.is_file()
        assert file_sha256(reference_path) == reference["sha256"]

    for source in manifest["sources"].values():
        assert source["url"].startswith("https://")
        assert source["size_bytes"] > 0
        assert len(source["sha256"]) == 64


def test_reference_parsers_cover_declared_speakers_and_text() -> None:
    manifest = yaml.safe_load((REGRESSION_ROOT / "manifest.yaml").read_text())

    for fixture in manifest["fixtures"]:
        spans = evaluate.reference_spans(fixture)
        assert spans
        assert all(span.start_ms < span.end_ms for span in spans)
        assert evaluate.normalize("".join(span.text for span in spans))
        if fixture["reference"]["quality"] == "gold":
            assert len({span.speaker for span in spans}) == fixture["speakers"]["count"]


def test_metrics_distinguish_text_and_speaker_errors() -> None:
    counts = evaluate.edit_counts("今天天气很好", "今天天气好")
    assert counts["deletions"] == 1
    assert counts["cer"] == 1 / 6

    reference = {"female": "天气很好", "male": "是的"}
    swapped = {"S01": "是的", "S02": "天气很好"}
    assert evaluate.permutation_cer(reference, swapped) == 0

    reference_spans = [
        evaluate.Span(0, 1000, "female", "天气很好"),
        evaluate.Span(1000, 2000, "male", "是的"),
    ]
    perfect = [
        evaluate.Span(0, 1000, "S02", ""),
        evaluate.Span(1000, 2000, "S01", ""),
    ]
    assert evaluate.diarization_error_rate(reference_spans, perfect) == 0

    unaligned = {
        "segments": [
            {
                "start_ms": 0,
                "end_ms": 1000,
                "speakers": [],
                "tokens": [{"text": "天气", "start_ms": None, "end_ms": None, "speakers": []}],
            }
        ]
    }
    assert evaluate.token_text_by_speaker(unaligned, 0, 1000) == {"unknown": "天气"}


def test_first_channel_pcm_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    destination = tmp_path / "destination.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(2)
        audio.writeframes(b"\x01\x00\x11\x00\x02\x00\x12\x00")

    prepare.first_channel_pcm(source, destination, 1)

    with wave.open(str(destination), "rb") as audio:
        assert audio.getparams().nchannels == 1
        assert audio.getparams().framerate == 2
        assert audio.readframes(2) == b"\x01\x00\x02\x00"
