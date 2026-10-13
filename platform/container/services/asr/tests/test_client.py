import asyncio
import wave
from array import array
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from client.asr import prepare, process, run, write_response

RECIPES = ("narration/qwen", "narration/firered")


def payload(*, recipes: tuple[str, ...] = RECIPES, status: str = "completed") -> dict:
    return {
        "results": [
            {
                "recipe": recipe,
                "status": status,
                "error": None,
                "segments": [
                    {
                        "start_ms": 100,
                        "end_ms": 1200,
                        "text": "测试。",
                        "speakers": ["S01"],
                        "flags": [],
                    }
                ],
                "warnings": [],
            }
            for recipe in recipes
        ],
        "evidence": {"filename": "recording.wav"},
        "trace": {"schema_version": 3, "status": "completed", "duration_ms": 1200, "events": []},
    }


def test_each_invocation_transcribes_without_saved_client_state(tmp_path: Path) -> None:
    source = tmp_path / "recording.wav"
    write_wav(source)
    output = tmp_path / "output"
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, json=payload())

    async def invoke() -> None:
        async with httpx.AsyncClient(
            base_url="http://asr", transport=httpx.MockTransport(respond)
        ) as client:
            for _ in range(2):
                assert await process(
                    client, source, output, options='{"scenario":"narration"}', overwrite=True
                )
                assert "narration/qwen" in (output / "index.md").read_text()
                assert "测试。" in (output / "narration--qwen.md").read_text()
                assert (
                    '"evidence": "evidence.json"' in (output / "narration--qwen.json").read_text()
                )
                assert "trace.html" in (output / "index.md").read_text()
                assert 'id="trace-data"' in (output / "trace.html").read_text()
                assert "Model Timeline" in (output / "trace.html").read_text()
                assert len(list(output.iterdir())) == 8
                assert not (output / ".asr-state.json").exists()

    asyncio.run(invoke())
    assert calls == [("POST", "/transcribe")] * 2


def test_recipe_names_cannot_escape_output_directory(tmp_path: Path) -> None:
    destination = tmp_path / "output"
    destination.mkdir()
    with pytest.raises(ValueError, match="invalid or duplicate recipe"):
        write_response(payload(recipes=("../outside",)), destination)
    assert not (tmp_path / "outside.json").exists()


def test_markdown_does_not_preserve_model_line_end_whitespace(tmp_path: Path) -> None:
    destination = tmp_path / "output"
    destination.mkdir()
    response = payload(recipes=("narration/qwen",))
    response["results"][0]["segments"][0]["text"] = "第一行 \n第二行\t"

    write_response(response, destination)

    document = (destination / "narration--qwen.md").read_text()
    assert "第一行\n第二行\n" in document
    assert all(line == line.rstrip() for line in document.splitlines())


def test_trace_report_escapes_embedded_html(tmp_path: Path) -> None:
    destination = tmp_path / "output"
    destination.mkdir()
    response = payload()
    response["trace"]["events"] = [
        {
            "kind": "phase",
            "name": "upload",
            "status": "failed",
            "started_ms": 0,
            "duration_ms": 1,
            "error": "</script><script>alert(1)</script>",
        }
    ]

    write_response(response, destination)

    report = (destination / "trace.html").read_text()
    assert "</script><script>alert(1)</script>" not in report
    assert r"\u003c/script\u003e\u003cscript\u003ealert(1)\u003c/script\u003e" in report


def test_cli_controls_file_concurrency(tmp_path: Path) -> None:
    source = tmp_path / "recordings"
    source.mkdir()
    for i in range(4):
        write_wav(source / f"{i}.wav")
    active = 0
    peak = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.03)
        active -= 1
        return httpx.Response(200, json=payload())

    client = httpx.AsyncClient(base_url="http://asr", transport=httpx.MockTransport(respond))
    with patch("client.asr.httpx.AsyncClient", return_value=client):
        assert asyncio.run(
            run(source, "http://asr", tmp_path / "output", 2, '{"scenario":"narration"}', False)
        )
    assert peak == 2


def write_wav(path: Path, value: int = 1000, frames: int = 16000) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(array("h", [value] * frames).tobytes())


def test_two_tracks_preserve_identity_offset_and_longer_tail(tmp_path: Path) -> None:
    first, second, target = (tmp_path / name for name in ("first.wav", "second.wav", "out.wav"))
    write_wav(first, 1000, 16000)
    write_wav(second, 2000, 32000)
    asyncio.run(prepare(first, target, separate=True, second=second, offset_ms=500))
    with wave.open(str(target), "rb") as audio:
        assert audio.getnchannels() == 2
        assert audio.getnframes() == 40000
        samples = array("h", audio.readframes(audio.getnframes()))
    assert samples[0:2] == array("h", [1000, 0])
    assert samples[16000:16002] == array("h", [1000, 2000])
    assert samples[-2:] == array("h", [0, 2000])
