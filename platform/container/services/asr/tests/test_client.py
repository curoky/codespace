import asyncio
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from client.asr import process, run, write_response

RECIPES = (
    "01-qwen-fusion",
    "02-firered-fusion",
    "03-moss-td",
    "04-vibevoice",
    "05-qwen-nemotron",
)


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
        "trace": {
            "schema_version": 1,
            "status": "completed" if status == "completed" else "partial",
            "duration_ms": 1200,
            "events": [],
        },
    }


def test_each_invocation_transcribes_without_saved_client_state(tmp_path: Path) -> None:
    source = tmp_path / "recording.wav"
    source.write_bytes(b"audio")
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
                assert await process(client, source, output, options="{}", overwrite=True)
                assert "01-qwen-fusion" in (output / "index.md").read_text()
                assert "测试。" in (output / "01-qwen-fusion.md").read_text()
                assert '"evidence": "evidence.json"' in (output / "01-qwen-fusion.json").read_text()
                assert "trace.html" in (output / "index.md").read_text()
                assert 'id="trace-data"' in (output / "trace.html").read_text()
                assert len(list(output.iterdir())) == 14
                assert not (output / ".asr-state.json").exists()

    asyncio.run(invoke())
    assert calls == [("POST", "/transcribe")] * 2


def test_recipe_names_cannot_escape_output_directory(tmp_path: Path) -> None:
    destination = tmp_path / "output"
    destination.mkdir()
    with pytest.raises(ValueError, match="invalid or duplicate recipe"):
        write_response(payload(recipes=("../outside",)), destination)
    assert not (tmp_path / "outside.json").exists()


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
        (source / f"{i}.wav").write_bytes(b"audio")
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
        assert asyncio.run(run(source, "http://asr", tmp_path / "output", 2, "{}", False))
    assert peak == 2
