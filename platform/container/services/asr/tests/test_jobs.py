import asyncio
import io
import json
import shutil
import time
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from ops.processes import GPU
from ops.scheduler import Scheduler
from protocol import InferenceResult, Span, Token
from server.api import create_app
from server.audio import wav_duration
from server.config import Config, ResourceConfig
from server.recipes import RECIPE_IDS


async def control(action: str, model: str) -> None:
    return None


async def inventory(pool: str | list[str]) -> list[GPU]:
    return [GPU(id=f"GPU-{i}", index=str(i), total_mib=80000, free_mib=80000) for i in range(2)]


def wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 32000)
    return buffer.getvalue()


async def decode(source: Path, work: Path, *, channel: int | None = None) -> tuple[Path, int, str]:
    destination = work / "audio.wav"
    shutil.copyfile(source, destination)
    return (
        destination,
        wav_duration(destination),
        '{"streams":[{"codec_type":"audio","channels":1}]}',
    )


def runtime(tmp_path: Path, *, broken: str | None = None) -> Scheduler:
    models = tmp_path / "models"
    source = Path(__file__).resolve().parents[1] / "models"
    for original in source.iterdir():
        if not original.is_dir() or not (original / "run").is_file():
            continue
        directory = models / original.name
        directory.mkdir(parents=True)
        for name in ("uv.lock", "run", "client.py", "download_model.sh"):
            shutil.copyfile(original / name, directory / name)
    config = Config(
        data_dir=tmp_path / "data",
        models_dir=models,
        runtime_dir=tmp_path / "run",
        resources=ResourceConfig(wait_seconds=3),
    )
    config.runtime_dir.mkdir()
    scheduler = Scheduler(config, control=control, inventory=inventory)

    def respond(request: httpx.Request) -> httpx.Response:
        instance = next(
            i for i in scheduler.instances.values() if httpx.URL(i.url).port == request.url.port
        )
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ready"})
        if instance.spec.id == broken:
            return httpx.Response(500, json={"error": "model failed"})
        if instance.spec.protocol == "sdk-http":
            payload = json.loads(request.content)
            role = instance.spec.role
            if role == "align":
                chars = payload["text"].rstrip("。")
                duration = wav_duration(Path(payload["audio"]))
                tokens = [
                    Token(
                        text=char,
                        start_ms=round(i * duration / len(chars)),
                        end_ms=round((i + 1) * duration / len(chars)),
                    )
                    for i, char in enumerate(chars)
                ]
                result = InferenceResult(text=payload["text"], tokens=tokens)
            elif role in ("vad", "diarize"):
                result = InferenceResult(
                    spans=[
                        Span(
                            start_ms=100,
                            end_ms=1900,
                            speaker="local0" if role == "diarize" else None,
                        )
                    ]
                )
            elif role == "punctuate":
                result = InferenceResult(text=payload["text"].rstrip("。") + "。")
            else:
                result = InferenceResult(text="你好世界。")
            return httpx.Response(200, json=result.model_dump(mode="json"))
        text = "你好世界。"
        if instance.spec.id == "moss-td":
            text = "[0.1][S01]你好世界。[1.9]"
        if instance.spec.id == "vibevoice":
            text = '[{"Start":0.1,"End":1.9,"Speaker":0,"Content":"你好世界。"}]'
        event = {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}
        return httpx.Response(
            200,
            text="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    asyncio.run(scheduler.http.aclose())
    scheduler.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    return scheduler


def wait(client: TestClient, job: str) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result: dict[str, object] = client.get(f"/jobs/{job}").json()
        if result["state"] in ("completed", "partial_failed", "failed"):
            return result
        time.sleep(0.01)
    raise AssertionError("job did not terminate")


def test_one_upload_produces_five_documents_and_resume_is_idempotent(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    with (
        patch("server.jobs.decode", decode),
        TestClient(create_app(scheduler.config, scheduler)) as client,
    ):
        response = client.post(
            "/jobs", files={"file": ("会议.wav", wav())}, headers={"Idempotency-Key": "a" * 64}
        )
        assert response.status_code == 202
        job = response.json()["id"]
        assert wait(client, job)["state"] == "completed"
        duplicate = client.post(
            "/jobs", files={"file": ("会议.wav", wav())}, headers={"Idempotency-Key": "a" * 64}
        )
        assert duplicate.json()["id"] == job
        archive = client.get(f"/jobs/{job}/download")
        with zipfile.ZipFile(io.BytesIO(archive.content)) as bundle:
            assert len(bundle.namelist()) == 11
            for recipe in RECIPE_IDS:
                result = json.loads(bundle.read(f"{recipe}.json"))
                assert result["status"] == "completed"
                assert "".join(s["text"] for s in result["segments"]) == "你好世界。"
        assert not scheduler.instances["whisper-large-v3"].running
        assert not scheduler.instances["moss-audio"].running


def test_failed_asr_keeps_joint_documents_and_returns_partial_failure(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path, broken="firered-llm")
    with (
        patch("server.jobs.decode", decode),
        TestClient(create_app(scheduler.config, scheduler)) as client,
    ):
        job = client.post("/jobs", files={"file": ("a.wav", wav())}).json()["id"]
        result = wait(client, job)
        assert result["state"] == "partial_failed"
        assert result["recipes"] == dict(
            zip(
                RECIPE_IDS,
                ["completed", "failed", "completed", "completed", "completed"],
                strict=True,
            )
        )
        assert client.get(f"/jobs/{job}/download").status_code == 200


def test_waiting_for_multiple_gpus_is_cancellable_and_reclaims_idle_model(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)

    async def run() -> None:
        first = await scheduler.acquire("qwen3-asr-1.7b")
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(scheduler.acquire("firered-llm"), 0.05)
        await scheduler.release(first)
        second = await scheduler.acquire("firered-llm")
        assert not first.running
        assert len(second.devices) == 2
        await scheduler.release(second)
        await scheduler.close()

    asyncio.run(run())


def test_separate_channels_still_produces_five_documents(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)

    async def stereo(
        source: Path, work: Path, *, channel: int | None = None
    ) -> tuple[Path, int, str]:
        audio, duration, _ = await decode(source, work, channel=channel)
        return audio, duration, '{"streams":[{"codec_type":"audio","channels":2}]}'

    with (
        patch("server.jobs.decode", stereo),
        TestClient(create_app(scheduler.config, scheduler)) as client,
    ):
        job = client.post(
            "/jobs",
            files={"file": ("a.wav", wav())},
            data={"options": '{"separate_channels":true}'},
        ).json()["id"]
        assert wait(client, job)["state"] == "completed"
        result = client.get(f"/jobs/{job}/artifacts/01-qwen-fusion.json").json()
        assert {s["channel"] for s in result["segments"]} == {0, 1}
        assert {p for s in result["segments"] for p in s["speakers"]} == {"C1-S01", "C2-S01"}
