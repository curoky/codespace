import ast
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from models import start
from scheduler.config import read_config
from scheduler.scenarios import RECIPES

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("scenario", RECIPES)
def test_scene_deployment_covers_exact_recipe_dependencies(scenario: str) -> None:
    defaults = read_config(ROOT / "scheduler/scheduler.yaml")
    known = {instance.model for instance in defaults.instances}
    required = set()
    for recipe in RECIPES[scenario]:
        tree = ast.parse((ROOT / f"scheduler/scenarios/{scenario}/{recipe}.py").read_text())
        required.update(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value in known
        )
    directory = ROOT / "deployment" / scenario
    environment = dict(
        line.split("=", 1) for line in (directory / "models.env").read_text().splitlines()
    )
    selected = environment["ASR_MODELS"].split(",")
    assert len(selected) == len(set(selected))
    assert set(selected) == required
    placement = json.loads(environment["ASR_PLACEMENT"])
    assert set(placement) == required - {"firered-vad", "firered-punc"}
    assert all(
        devices and all(isinstance(device, int) and device >= 0 for device in devices)
        for devices in placement.values()
    )
    assert len(placement["firered-llm"]) == 2
    config = read_config(directory / "scheduler.yaml")
    assert {instance.model for instance in config.instances} == required
    assert config.instances == [
        instance for instance in defaults.instances if instance.model in required
    ]


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
