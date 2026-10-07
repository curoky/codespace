import asyncio
import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from client.asr import extract, process, run


def test_each_invocation_transcribes_without_saved_client_state(tmp_path: Path) -> None:
    source = tmp_path / "recording.wav"
    source.write_bytes(b"audio")
    output = tmp_path / "output"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("index.md", "transcript")
        bundle.writestr("01.json", '{"status":"completed"}')
        bundle.writestr("evidence.json", "{}")
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        return httpx.Response(200, content=archive.getvalue())

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://asr", transport=httpx.MockTransport(respond)
        ) as client:
            for _ in range(2):
                assert await process(client, source, output, options="{}", overwrite=True)
                assert (output / "index.md").read_text() == "transcript"
                assert not (output / ".asr-state.json").exists()

    asyncio.run(run())
    assert calls == [("POST", "/transcribe")] * 2


def test_archive_paths_cannot_escape_output_directory(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.md", "bad")
    with pytest.raises(ValueError, match="invalid artifact path"):
        extract(archive, tmp_path)
    assert not (tmp_path.parent / "outside.md").exists()


def test_cli_controls_file_concurrency(tmp_path: Path) -> None:
    source = tmp_path / "recordings"
    source.mkdir()
    for i in range(4):
        (source / f"{i}.wav").write_bytes(b"audio")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("01.json", '{"status":"completed"}')
    active = 0
    peak = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.03)
        active -= 1
        return httpx.Response(200, content=archive.getvalue())

    client = httpx.AsyncClient(base_url="http://asr", transport=httpx.MockTransport(respond))
    with patch("client.asr.httpx.AsyncClient", return_value=client):
        assert asyncio.run(run(source, "http://asr", tmp_path / "output", 2, "{}", False))
    assert peak == 2
