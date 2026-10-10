import asyncio
import io
import json
import shutil
import wave
from pathlib import Path
from unittest.mock import patch

import httpx2
from fastapi.testclient import TestClient

from ops.processes import GPU, GPUUtilization
from ops.scheduler import Scheduler
from protocol import InferenceRequest, InferenceResult, Span, Token
from server.api import create_app
from server.audio import Window, wav_duration
from server.config import read_config
from server.inference import Inference
from server.recipes import RECIPE_IDS, Options, Pipeline
from server.tracing import Trace
from server.transcribe import run_recipes
from server.transcript import Segment, Transcript


async def control(action: str, model: str) -> None:
    return None


async def inventory() -> list[GPU]:
    return [GPU(id=f"GPU-{i}", index=str(i), total_mib=80000, free_mib=80000) for i in range(6)]


async def utilization(device_ids: list[str]) -> list[GPUUtilization]:
    return [
        GPUUtilization(
            id=device_id,
            index=device_id.removeprefix("GPU-"),
            gpu_percent=50,
            memory_percent=25,
            memory_used_mib=40000,
            power_watts=300,
        )
        for device_id in device_ids
    ]


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
        config,
        runtime_dir=tmp_path / "run",
        control=control,
        inventory=inventory,
        utilization=utilization,
    )

    def respond(request: httpx2.Request) -> httpx2.Response:
        instance = next(
            i for i in scheduler.instances.values() if httpx2.URL(i.url).port == request.url.port
        )
        if request.url.path == "/health":
            return httpx2.Response(200, json={"status": "ready"})
        if instance.model == broken:
            return httpx2.Response(500, json={"error": "model failed"})
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
                assert not any(mark in payload["text"] for mark in "，。\uff01\uff1f；：、,.!?;…")
                result = InferenceResult(text=payload["text"].rstrip("。") + "。")
            else:
                result = InferenceResult(text="你好世界。")
            return httpx2.Response(200, json=result.model_dump(mode="json"))
        text = "你好世界。" if instance.model != "whisper-large-v3" else "您好世界。"
        if instance.model == "moss-td":
            text = "[0.1][S01]你好世界。[1.9]"
        if instance.model == "vibevoice":
            text = '[{"Start":0.1,"End":1.9,"Speaker":0,"Content":"你好世界。"}]'
        event = {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}
        return httpx2.Response(
            200,
            text="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )

    asyncio.run(scheduler.http.aclose())
    scheduler.http = httpx2.AsyncClient(transport=httpx2.MockTransport(respond))
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
        assert trace["schema_version"] == 2
        assert trace["status"] == "completed"
        assert trace["duration_ms"] >= 0
        assert trace["gpu_sample_interval_ms"] == 1000
        assert trace["gpu_samples"]
        assert [device["index"] for device in trace["gpu_samples"][0]["devices"]] == [
            "0",
            "1",
            "2",
            "3",
            "4",
            "5",
        ]
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
        assert scheduler.instances["moss-audio"].devices == ["GPU-5"]
        assert scheduler.instances["moss-td"].devices == ["GPU-2"]
        assert scheduler.instances["vibevoice-a"].devices == ["GPU-3"]
        assert scheduler.instances["vibevoice-b"].devices == ["GPU-4"]
        assert scheduler.instances["qwen3-aligner-review"].devices == ["GPU-4"]
        assert scheduler.instances["qwen3-aligner-recipe"].devices == ["GPU-0"]
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


def test_instance_pool_runs_two_replicas_and_queues_the_third_call(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)

    async def run() -> None:
        first = await scheduler.acquire("vibevoice")
        second = await scheduler.acquire("vibevoice")
        assert {first.id, second.id} == {"vibevoice-a", "vibevoice-b"}
        waiting = asyncio.create_task(scheduler.acquire("vibevoice"))
        await asyncio.sleep(0)
        other = await asyncio.wait_for(scheduler.acquire("firered-llm"), 0.2)
        assert not waiting.done()
        await scheduler.release(other)
        await scheduler.release(first)
        third = await waiting
        assert third is first
        await scheduler.release(third)
        await scheduler.release(second)
        await scheduler.close()

    asyncio.run(run())


def test_concurrent_identical_calls_share_result_after_model_lock(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    inference = Inference(scheduler, tmp_path)
    calls = 0

    async def infer(
        client: httpx2.AsyncClient, url: str, request: InferenceRequest
    ) -> InferenceResult:
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


def test_recipe_dag_starts_01_to_04_together_and_05_after_only_01(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    pipeline = Pipeline(
        scheduler.config,
        Inference(scheduler, tmp_path, Trace()),
        tmp_path / "audio.wav",
        1000,
        Options(),
    )
    started: set[str] = set()
    completed: set[str] = set()
    first_four_started = asyncio.Event()
    release_qwen = asyncio.Event()
    release_others = asyncio.Event()
    nemotron_started = asyncio.Event()

    async def prepare() -> None:
        return None

    async def recipe(name: str) -> Transcript:
        started.add(name)
        if len(started) == 4:
            first_four_started.set()
        await (release_qwen if name == RECIPE_IDS[0] else release_others).wait()
        completed.add(name)
        return Transcript(recipe=name)

    async def fusion(name: str, model: str) -> Transcript:
        return await recipe(name)

    async def joint(name: str, model: str) -> Transcript:
        return await recipe(name)

    async def nemotron(source: Transcript) -> Transcript:
        assert source.recipe == RECIPE_IDS[0]
        assert completed == {RECIPE_IDS[0]}
        nemotron_started.set()
        return Transcript(recipe=RECIPE_IDS[4])

    pipeline.prepare = prepare  # type: ignore[method-assign]
    pipeline.first_pass = prepare  # type: ignore[method-assign]
    pipeline.review = prepare  # type: ignore[method-assign]
    pipeline.fusion = fusion  # type: ignore[method-assign]
    pipeline.joint = joint  # type: ignore[method-assign]
    pipeline.nemotron = nemotron  # type: ignore[method-assign]

    async def run() -> None:
        task = asyncio.create_task(run_recipes(pipeline))
        await asyncio.wait_for(first_four_started.wait(), 0.2)
        assert started == set(RECIPE_IDS[:4])
        release_qwen.set()
        await asyncio.wait_for(nemotron_started.wait(), 0.2)
        assert completed == {RECIPE_IDS[0]}
        release_others.set()
        results = await task
        assert [result.recipe for result in results] == list(RECIPE_IDS)
        await scheduler.close()

    asyncio.run(run())


def test_joint_windows_run_concurrently_and_merge_in_time_order(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(wav(400))
    pipeline = Pipeline(scheduler.config, Inference(scheduler, tmp_path), audio, 400000, Options())
    pipeline.activity = [Span(start_ms=0, end_ms=400000)]
    active = 0
    maximum = 0

    async def recognize(model: str, window: Window, *, step: str) -> InferenceResult:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep((400000 - window.start_ms) / 10_000_000)
        active -= 1
        return InferenceResult(
            spans=[
                Span(
                    start_ms=0,
                    end_ms=window.end_ms - window.start_ms,
                    text=str(window.core_start_ms),
                    speaker="0",
                )
            ]
        )

    async def finalize(
        segment: Segment,
        window: Window,
        speakers: list[Span],
        *,
        step: str,
        punctuate: bool = True,
    ) -> list[Segment]:
        segment.start_ms = window.core_start_ms
        segment.end_ms = window.core_end_ms
        return [segment]

    pipeline.recognize = recognize  # type: ignore[method-assign]
    pipeline.finalize_segment = finalize  # type: ignore[method-assign]

    async def run() -> Transcript:
        result = await pipeline.joint(RECIPE_IDS[3], "vibevoice")
        await scheduler.close()
        return result

    result = asyncio.run(run())
    assert maximum == 2
    assert [segment.start_ms for segment in result.segments] == sorted(
        segment.start_ms for segment in result.segments
    )


def test_joint_alignment_failure_retries_without_boundary_padding(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    pipeline = Pipeline(scheduler.config, Inference(scheduler, tmp_path), audio, 400000, Options())
    pipeline.activity = [Span(start_ms=0, end_ms=400000)]
    seen: list[Window] = []

    async def recognize(model: str, window: Window, *, step: str) -> InferenceResult:
        seen.append(window)
        return InferenceResult(
            spans=[
                Span(
                    start_ms=0,
                    end_ms=window.end_ms - window.start_ms,
                    text="完整原文",
                    speaker="0",
                )
            ]
        )

    async def align(text: str, window: Window, *, step: str, instance_id: str) -> list[Token]:
        return [Token(text=text, start_ms=None, end_ms=None)]

    pipeline.recognize = recognize  # type: ignore[method-assign]
    pipeline.align = align  # type: ignore[method-assign]

    async def run() -> Transcript:
        result = await pipeline.joint(RECIPE_IDS[3], "vibevoice")
        await scheduler.close()
        return result

    result = asyncio.run(run())
    assert result.status == "completed"
    assert result.segments
    assert all(not segment.tokens for segment in result.segments)
    assert any(
        window.start_ms == window.core_start_ms and window.end_ms == window.core_end_ms
        for window in seen
    )


def test_joint_only_aligns_segments_crossing_core_boundary(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    pipeline = Pipeline(scheduler.config, Inference(scheduler, tmp_path), audio, 400000, Options())
    pipeline.activity = [Span(start_ms=0, end_ms=400000)]
    pipeline.speakers = [Span(start_ms=0, end_ms=400000, speaker="S01")]
    aligned: list[Window] = []

    async def recognize(model: str, window: Window, *, step: str) -> InferenceResult:
        duration = window.end_ms - window.start_ms
        return InferenceResult(
            spans=[
                Span(start_ms=2000, end_ms=3000, text="内部原文", speaker="0"),
                Span(
                    start_ms=duration - 1500,
                    end_ms=duration,
                    text="边界原文",
                    speaker="0",
                ),
            ]
        )

    async def finalize(
        segment: Segment,
        window: Window,
        speakers: list[Span],
        *,
        step: str,
        punctuate: bool = True,
    ) -> list[Segment]:
        aligned.append(window)
        segment.end_ms = window.core_end_ms
        return [segment]

    pipeline.recognize = recognize  # type: ignore[method-assign]
    pipeline.finalize_segment = finalize  # type: ignore[method-assign]

    async def run() -> Transcript:
        result = await pipeline.joint(RECIPE_IDS[3], "vibevoice")
        await scheduler.close()
        return result

    result = asyncio.run(run())
    assert any(segment.text == "内部原文" for segment in result.segments)
    assert all(segment.speakers == ["S01"] for segment in result.segments)
    assert aligned
    assert all(window.core_end_ms < window.end_ms for window in aligned)
    assert all(window.core_start_ms < window.end_ms for window in aligned)


def test_joint_retries_failed_windows_to_eight_second_exact_cores(tmp_path: Path) -> None:
    scheduler = runtime(tmp_path)
    audio = tmp_path / "audio.wav"
    audio.write_bytes(b"")
    pipeline = Pipeline(scheduler.config, Inference(scheduler, tmp_path), audio, 178000, Options())
    pipeline.activity = [Span(start_ms=0, end_ms=178000)]
    seen: list[Window] = []

    async def recognize(model: str, window: Window, *, step: str) -> InferenceResult:
        seen.append(window)
        if window.core_end_ms - window.core_start_ms > 8000:
            raise ValueError("persistent generation failure")
        return InferenceResult(
            spans=[
                Span(
                    start_ms=window.core_start_ms - window.start_ms,
                    end_ms=window.core_end_ms - window.start_ms,
                    text="缩窗恢复",
                    speaker="0",
                )
            ]
        )

    pipeline.recognize = recognize  # type: ignore[method-assign]

    async def run() -> Transcript:
        result = await pipeline.joint(RECIPE_IDS[3], "vibevoice")
        await scheduler.close()
        return result

    result = asyncio.run(run())
    assert result.status == "completed"
    assert result.segments
    assert any(window.core_end_ms - window.core_start_ms <= 8000 for window in seen)
    assert all(segment.text == "缩窗恢复" for segment in result.segments)


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


def test_review_speculates_moss_concurrently_but_only_keeps_needed_result(tmp_path: Path) -> None:
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
        active.add(model)
        maximum = max(maximum, len(active))
        await asyncio.sleep(0.01)
        active.remove(model)
        completed.add(model)
        return InferenceResult(text="主复听一致" if model != "moss-audio" else "MOSS 不一致")

    async def align(text: str, window: Window, *, step: str, instance_id: str) -> list[Token]:
        assert instance_id == "qwen3-aligner-review"
        return [Token(text=text, start_ms=0, end_ms=1000)]

    pipeline.recognize = recognize  # type: ignore[method-assign]
    pipeline.align = align  # type: ignore[method-assign]

    async def run() -> None:
        await pipeline.review()
        await scheduler.close()

    asyncio.run(run())
    assert maximum == 4
    assert completed == {
        "qwen3-asr-1.7b",
        "firered-llm",
        "whisper-large-v3",
        "moss-audio",
    }
    assert pipeline.reviewed[window.model_dump_json()] == {
        "qwen3-asr-1.7b": "主复听一致",
        "firered-llm": "主复听一致",
        "whisper-large-v3": "主复听一致",
    }
