import asyncio
import io
import json
import shutil
import wave
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from ops.processes import GPU
from ops.scheduler import Scheduler
from protocol import InferenceRequest, InferenceResult, Span, Token
from server.api import create_app
from server.audio import Window, wav_duration
from server.config import read_config
from server.inference import Inference
from server.recipes import RECIPE_IDS, Options, Pipeline


async def control(action: str, model: str) -> None:
    return None


async def inventory() -> list[GPU]:
    return [GPU(id=f"GPU-{i}", index=str(i), total_mib=80000, free_mib=80000) for i in range(5)]


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
    config = read_config(Path(__file__).resolve().parents[1] / "server/server.yaml")
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


def test_one_request_returns_five_results_and_shared_evidence(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    work = tmp_path / "requests"
    with (
        patch("server.transcribe.decode", decode),
        TestClient(create_app(scheduler.config, scheduler, work_dir=work)) as client,
    ):
        response = client.post("/transcribe", files={"file": ("会议.wav", wav())})
        assert response.status_code == 200
        payload = response.json()
        assert [result["recipe"] for result in payload["results"]] == list(RECIPE_IDS)
        for result in payload["results"]:
            assert result["status"] == "completed"
            assert "".join(s["text"] for s in result["segments"]) == "你好世界。"
            assert "evidence" not in result
        evidence = payload["evidence"]
        assert evidence["filename"] == "会议.wav"
        records = evidence["channels"]["mono"]["raw_responses"]
        keys = [(r["model"], json.dumps(r["request"], sort_keys=True)) for r in records]
        assert len(keys) == len(set(keys))
        trace = payload["trace"]
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
        assert all("model_queue_ms" in event for event in model_events)
        assert all(
            "gpu_queue_ms" not in event and "startup_ms" not in event for event in model_events
        )
        assert all(event["input_summary"] for event in model_events)
        assert all(event["output_summary"] for event in model_events)
        assert list(work.iterdir()) == []
        assert all(instance.running for instance in scheduler.instances.values())


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
        payload = response.json()
        statuses = [result["status"] for result in payload["results"]]
        trace = payload["trace"]
        assert statuses == ["completed", "failed", "completed", "completed", "completed"]
        assert trace["status"] == "partial"
        assert any(
            event["kind"] == "model"
            and event["model"] == "firered-llm"
            and event["status"] == "failed"
            for event in trace["events"]
        )


def test_static_placement_starts_all_models_on_configured_devices(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    actions: list[tuple[str, str]] = []

    async def control(action: str, model: str) -> None:
        actions.append((action, model))

    scheduler.control = control

    async def run() -> None:
        await scheduler.initialize()
        assert scheduler.instances["firered-llm"].devices == ["GPU-0", "GPU-1"]
        assert scheduler.instances["moss-audio"].devices == ["GPU-0"]
        assert scheduler.instances["moss-td"].devices == ["GPU-2"]
        assert scheduler.instances["vibevoice"].devices == ["GPU-3"]
        assert scheduler.instances["qwen3-aligner"].devices == ["GPU-4"]
        assert all(instance.running for instance in scheduler.instances.values())
        await scheduler.close()
        assert all(instance.running for instance in scheduler.instances.values())

    asyncio.run(run())
    models = list(scheduler.instances)
    assert actions == (
        [("stop", model) for model in models] + [("start", model) for model in models]
    )


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
        for result in response.json()["results"]:
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


def test_different_models_can_run_concurrently(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)

    async def run() -> None:
        first = await scheduler.acquire("qwen3-asr-1.7b")
        waiting = asyncio.create_task(scheduler.acquire("qwen3-asr-1.7b"))
        await asyncio.sleep(0)
        other = await asyncio.wait_for(scheduler.acquire("firered-llm"), 0.2)
        assert not waiting.done()
        await scheduler.release(other)
        await scheduler.release(first)
        second = await waiting
        await scheduler.release(second)
        await scheduler.close()

    asyncio.run(run())


def test_concurrent_identical_calls_share_result_after_model_lock(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    inference = Inference(scheduler, tmp_path)
    calls = 0

    async def infer(client: httpx.AsyncClient, request: InferenceRequest) -> InferenceResult:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return InferenceResult(text="共享结果")

    scheduler.instances["qwen3-asr-1.7b"].client = infer

    async def run() -> None:
        request = InferenceRequest(text="same")
        results = await asyncio.gather(
            inference.call("qwen3-asr-1.7b", request),
            inference.call("qwen3-asr-1.7b", request),
        )
        assert [result.text for result in results] == ["共享结果", "共享结果"]
        await scheduler.close()

    asyncio.run(run())
    assert calls == 1
    assert [event.cache_hit for event in inference.trace.events] == [False, True]


def test_review_processes_windows_by_model(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
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
    assert len(pipeline.reviewed) == 10
    for reviews in pipeline.reviewed.values():
        assert reviews == {
            "qwen3-asr-1.7b": "你好世界。",
            "firered-llm": "你好世界。",
            "whisper-large-v3": "您好世界。",
            "moss-audio": "你好世界。",
        }


def test_first_pass_runs_models_concurrently_but_windows_serially(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    pipeline = Pipeline(
        scheduler.config, Inference(scheduler, tmp_path), tmp_path / "audio.wav", 60000, Options()
    )
    pipeline.audio.write_bytes(wav(60))
    pipeline.chunks = [
        Window(start_ms=i, end_ms=i + 30000, core_start_ms=i, core_end_ms=i + 30000)
        for i in (0, 30000)
    ]
    active: set[str] = set()
    maximum = 0
    per_model: dict[str, int] = {}

    async def recognize(model: str, window: Window, *, step: str) -> InferenceResult:
        nonlocal maximum
        assert model not in active
        active.add(model)
        per_model[model] = per_model.get(model, 0) + 1
        maximum = max(maximum, len(active))
        await asyncio.sleep(0.01)
        active.remove(model)
        return InferenceResult(text=f"{model}-{window.start_ms}")

    pipeline.recognize = recognize  # type: ignore[method-assign]

    async def run() -> None:
        await pipeline.first_pass()
        await scheduler.close()

    asyncio.run(run())
    assert maximum == 4
    assert per_model == {
        "qwen3-asr-1.7b": 2,
        "firered-llm": 2,
        "sensevoice": 2,
        "paraformer": 2,
    }


def test_review_runs_primary_models_before_moss_audio(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(wav(30))
    pipeline = Pipeline(scheduler.config, Inference(scheduler, tmp_path), audio, 30000, Options())
    window = Window(start_ms=0, end_ms=30000, core_start_ms=0, core_end_ms=30000)
    pipeline.chunks = [window]
    pipeline.candidates = {window.model_dump_json(): {"qwen3-asr-1.7b": "甲", "firered-llm": "乙"}}
    active: set[str] = set()
    maximum = 0
    completed: set[str] = set()

    async def recognize(model: str, window: Window, *, step: str) -> InferenceResult:
        nonlocal maximum
        if model == "moss-audio":
            assert not active
            assert completed == {"qwen3-asr-1.7b", "firered-llm", "whisper-large-v3"}
        active.add(model)
        maximum = max(maximum, len(active))
        await asyncio.sleep(0.01)
        active.remove(model)
        completed.add(model)
        return InferenceResult(text=model)

    async def align(text: str, window: Window, *, step: str) -> list[Token]:
        return [Token(text=text, start_ms=0, end_ms=1000)]

    pipeline.recognize = recognize  # type: ignore[method-assign]
    pipeline.align = align  # type: ignore[method-assign]

    async def run() -> None:
        await pipeline.review()
        await scheduler.close()

    asyncio.run(run())
    assert maximum == 3
    assert completed == {
        "qwen3-asr-1.7b",
        "firered-llm",
        "whisper-large-v3",
        "moss-audio",
    }
