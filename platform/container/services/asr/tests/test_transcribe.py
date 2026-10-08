import asyncio
import io
import json
import shutil
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
from server.audio import Window, wav_duration
from server.config import Config, ResourceConfig
from server.inference import Inference
from server.recipes import RECIPE_IDS, Options, Pipeline


async def control(action: str, model: str) -> None:
    return None


async def inventory(pool: str | list[str]) -> list[GPU]:
    return [GPU(id=f"GPU-{i}", index=str(i), total_mib=80000, free_mib=80000) for i in range(2)]


def wav(seconds: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\0\0" * 16000 * seconds)
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
    config = Config(resources=ResourceConfig(wait_seconds=3))
    scheduler = Scheduler(
        config, runtime_dir=tmp_path / "run", control=control, inventory=inventory
    )

    def respond(request: httpx.Request) -> httpx.Response:
        instance = next(
            i for i in scheduler.instances.values() if httpx.URL(i.url).port == request.url.port
        )
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ready"})
        if instance.spec.id == broken:
            return httpx.Response(500, json={"error": "model failed"})
        if not request.url.path.startswith("/v1/"):
            payload = json.loads(request.content)
            if request.url.path == "/align":
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
            elif request.url.path in ("/vad", "/diarize"):
                result = InferenceResult(
                    spans=[
                        Span(
                            start_ms=100,
                            end_ms=1900,
                            speaker="local0" if request.url.path == "/diarize" else None,
                        )
                    ]
                )
            elif request.url.path == "/punctuate":
                result = InferenceResult(text=payload["text"].rstrip("。") + "。")
            else:
                result = InferenceResult(text="你好世界。")
            return httpx.Response(200, json=result.model_dump(mode="json"))
        text = "你好世界。" if instance.spec.id != "whisper-large-v3" else "您好世界。"
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


def test_one_request_returns_five_documents_and_shared_evidence(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    work = tmp_path / "requests"
    with (
        patch("server.transcribe.decode", decode),
        TestClient(create_app(scheduler.config, scheduler, work_dir=work)) as client,
    ):
        response = client.post("/transcribe", files={"file": ("会议.wav", wav())})
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            assert len(bundle.namelist()) == 13
            for recipe in RECIPE_IDS:
                result = json.loads(bundle.read(f"{recipe}.json"))
                assert result["status"] == "completed"
                assert "".join(s["text"] for s in result["segments"]) == "你好世界。"
                assert result["evidence"] == "evidence.json"
            evidence = json.loads(bundle.read("evidence.json"))
            assert evidence["filename"] == "会议.wav"
            records = evidence["channels"]["mono"]["raw_responses"]
            keys = [(r["model"], json.dumps(r["request"], sort_keys=True)) for r in records]
            assert len(keys) == len(set(keys))
            trace = json.loads(bundle.read("trace.json"))
            assert trace["schema_version"] == 1
            assert trace["status"] == "completed"
            assert trace["duration_ms"] >= 0
            assert {event["name"] for event in trace["events"] if event["kind"] == "phase"} >= {
                "upload",
                "decode",
                "prepare",
                "first_pass",
                "review",
                *("recipe." + recipe for recipe in RECIPE_IDS),
            }
            model_events = [
                event
                for event in trace["events"]
                if event["kind"] == "model" and not event["cache_hit"]
            ]
            assert {event["model"] for event in model_events} == {
                "firered-llm",
                "firered-punc",
                "firered-vad",
                "moss-td",
                "nemotron-diarization",
                "paraformer",
                "pyannote-community-1",
                "qwen3-aligner",
                "qwen3-asr-1.7b",
                "sensevoice",
                "vibevoice",
            }
            assert all(event["duration_ms"] >= event["inference_ms"] for event in model_events)
            assert all("gpu_queue_ms" in event for event in model_events)
            assert all(event["input_summary"] for event in model_events)
            assert all(event["output_summary"] for event in model_events)
        assert list(work.iterdir()) == []
        assert not scheduler.instances["whisper-large-v3"].running
        assert not scheduler.instances["moss-audio"].running


def test_failed_asr_keeps_joint_documents_and_returns_partial_failure(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path, broken="firered-llm")
    with (
        patch("server.transcribe.decode", decode),
        TestClient(
            create_app(scheduler.config, scheduler, work_dir=tmp_path / "requests")
        ) as client,
    ):
        response = client.post("/transcribe", files={"file": ("a.wav", wav())})
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            statuses = [json.loads(bundle.read(f"{r}.json"))["status"] for r in RECIPE_IDS]
            trace = json.loads(bundle.read("trace.json"))
        assert statuses == ["completed", "failed", "completed", "completed", "completed"]
        assert trace["status"] == "partial"
        assert any(
            event["kind"] == "model"
            and event["model"] == "firered-llm"
            and event["status"] == "failed"
            for event in trace["events"]
        )


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
        patch("server.transcribe.decode", stereo),
        TestClient(
            create_app(scheduler.config, scheduler, work_dir=tmp_path / "requests")
        ) as client,
    ):
        response = client.post(
            "/transcribe",
            files={"file": ("a.wav", wav())},
            data={"options": '{"separate_channels":true}'},
        )
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
            for recipe in RECIPE_IDS:
                result = json.loads(bundle.read(f"{recipe}.json"))
                assert {s["channel"] for s in result["segments"]} == {0, 1}
                assert {p for s in result["segments"] for p in s["speakers"]} == {
                    "C1-S01",
                    "C2-S01",
                }
                assert {s["speaker"] for s in result["speakers"]} == {"C1-S01", "C2-S01"}


def test_failed_request_cleans_temporary_audio(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path, broken="pyannote-community-1")
    work = tmp_path / "requests"
    with (
        patch("server.transcribe.decode", decode),
        TestClient(
            create_app(scheduler.config, scheduler, work_dir=work), raise_server_exceptions=False
        ) as client,
    ):
        assert client.post("/transcribe", files={"file": ("a.wav", wav())}).status_code == 500
        assert list(work.iterdir()) == []


def test_cpu_service_runs_while_gpu_request_waits(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)

    async def run() -> None:
        first = await scheduler.acquire("qwen3-asr-1.7b")
        waiting = asyncio.create_task(scheduler.acquire("firered-llm"))
        await asyncio.sleep(0)
        cpu = await asyncio.wait_for(scheduler.acquire("firered-punc"), 0.2)
        assert not waiting.done()
        await scheduler.release(cpu)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        await scheduler.release(first)
        await scheduler.close()

    asyncio.run(run())


def test_review_processes_windows_by_model_without_repeated_loading(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    starts: list[str] = []

    async def start(action: str, model: str) -> None:
        if action == "start":
            starts.append(model)

    async def four_gpus(pool: str | list[str]) -> list[GPU]:
        return [GPU(id=f"GPU-{i}", index=str(i), total_mib=80000, free_mib=80000) for i in range(4)]

    scheduler.control = start
    scheduler.inventory = four_gpus
    audio = tmp_path / "audio.wav"
    audio.write_bytes(wav(300))
    pipeline = Pipeline(scheduler.config, Inference(scheduler, tmp_path), audio, 300000, Options())
    pipeline.chunks = [
        Window(start_ms=i, end_ms=i + 30000, core_start_ms=i, core_end_ms=i + 30000)
        for i in range(0, 300000, 30000)
    ]
    pipeline.candidates = {
        w.model_dump_json(): {"qwen3-asr-1.7b": "你好世界", "firered-llm": "您好世界"}
        for w in pipeline.chunks
    }

    async def run() -> None:
        await pipeline.review()
        await scheduler.close()

    asyncio.run(run())
    assert len(starts) == 5
    assert len(pipeline.reviewed) == 10
    for reviews in pipeline.reviewed.values():
        assert reviews == {
            "qwen3-asr-1.7b": "你好世界。",
            "firered-llm": "你好世界。",
            "whisper-large-v3": "您好世界。",
            "moss-audio": "你好世界。",
        }
