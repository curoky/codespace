import asyncio
import io
import zipfile
from pathlib import Path

import httpx
import pytest

from client.asr import extract, process


def test_resume_redownloads_missing_artifacts_without_submitting_again(tmp_path: Path) -> None:
    source = tmp_path / "recording.wav"
    source.write_bytes(b"audio")
    output = tmp_path / "output"
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("index.md", "transcript")
    calls = {"submit": 0, "download": 0}
    status = {"id": "a" * 32, "state": "completed", "stage": "finished", "recipes": {}}

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            calls["submit"] += 1
            return httpx.Response(202, json=status)
        if request.url.path.endswith("/download"):
            calls["download"] += 1
            return httpx.Response(200, content=archive.getvalue())
        return httpx.Response(200, json=status)

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://asr", transport=httpx.MockTransport(respond)
        ) as client:
            for _ in range(2):
                assert await process(
                    client, source, output, deployment="v1", options="{}", overwrite=False
                )
                assert (output / "index.md").read_text() == "transcript"
                (output / "index.md").unlink()

    asyncio.run(run())
    assert calls == {"submit": 1, "download": 2}


def test_archive_paths_cannot_escape_output_directory(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../outside.md", "bad")
    with pytest.raises(ValueError, match="invalid artifact path"):
        extract(archive, tmp_path)
    assert not (tmp_path.parent / "outside.md").exists()
