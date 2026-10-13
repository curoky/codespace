from pathlib import Path
from unittest.mock import patch

import pytest

from models import start

ROOT = Path(__file__).parents[1]


def test_start_only_selects_requested_static_services(tmp_path: Path) -> None:
    (tmp_path / "ASR_MODELS").write_text("firered-vad,qwen3-asr-1.7b")
    (tmp_path / "ASR_PLACEMENT").write_text('{"qwen3-asr-1.7b":[2]}')
    original = Path

    def path(value: str) -> Path:
        return tmp_path / "models" if value == "/run/asr" else tmp_path / original(value).name

    with (
        patch("models.start.Path", side_effect=path),
        patch("models.start.subprocess.run") as launch,
        patch("models.start.signal.pause"),
    ):
        start.main()
    assert launch.call_args.args[0][-2:] == ["asr-firered-vad", "asr-qwen3-asr-1.7b"]
    assert sorted(p.name for p in (tmp_path / "models").iterdir()) == [
        "firered-vad",
        "qwen3-asr-1.7b",
    ]
    assert (tmp_path / "models/qwen3-asr-1.7b/CUDA_VISIBLE_DEVICES").read_text() == "2"
    assert (tmp_path / "models/qwen3-asr-1.7b/PORT").read_text() == "8009"


def test_missing_gpu_placement_fails_before_start(tmp_path: Path) -> None:
    (tmp_path / "ASR_MODELS").write_text("qwen3-asr-1.7b")
    with (
        patch("models.start.Path", side_effect=lambda value: tmp_path / Path(value).name),
        patch("models.start.subprocess.run") as launch,
        pytest.raises(ValueError, match="placement"),
    ):
        start.main()
    launch.assert_not_called()
