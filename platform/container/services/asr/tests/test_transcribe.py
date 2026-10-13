import asyncio
import io
import wave
from array import array
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from protocol import InferenceRequest, InferenceResult, Span, Token
from scheduler.api import create_app
from scheduler.config import Config, Instance
from scheduler.inference import Inference, Models
from scheduler.options import Options
from scheduler.scenarios import RECIPES, Recipe
from scheduler.scenarios.conversation_tracks import qwen
from scheduler.tracing import Trace
from scheduler.transcript import Segment, Transcript


def wav(channels: int = 1, seconds: int = 2) -> bytes:
    target = io.BytesIO()
    with wave.open(target, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(array("h", [1000, 2000][:channels] * 16000 * seconds).tobytes())
    return target.getvalue()


def test_selected_recipes_run_independently_and_concurrently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = 0
    ready = asyncio.Event()
    paths = []

    def recipe(name: str) -> Recipe:
        async def run(
            inference: Inference, source: Path, duration: int, options: Options
        ) -> Transcript:
            nonlocal entered
            paths.append(inference.work)
            entered += 1
            if entered == 2:
                ready.set()
            await asyncio.wait_for(ready.wait(), 1)
            return Transcript(
                recipe=f"narration/{name}",
                segments=[Segment(start_ms=0, end_ms=duration, text=name)],
            )

        return run

    monkeypatch.setitem(RECIPES, "narration", {"a": recipe("a"), "b": recipe("b")})
    with TestClient(create_app(Config(instances=[]), work_dir=tmp_path)) as client:
        response = client.post(
            "/transcribe",
            data={"options": '{"scenario":"narration"}'},
            files={"file": ("input.wav", wav(), "audio/wav")},
        )
    assert response.status_code == 200
    document = response.json()
    assert [r["recipe"] for r in document["results"]] == ["narration/a", "narration/b"]
    assert paths[0] != paths[1]
    assert set(document["evidence"]["recipes"]) == {"a", "b"}
    assert document["trace"]["schema_version"] == 3
    assert list(tmp_path.iterdir()) == []


def test_scenario_requires_explicit_track_layout(tmp_path: Path) -> None:
    with TestClient(create_app(Config(instances=[]), work_dir=tmp_path)) as client:
        response = client.post(
            "/transcribe",
            data={"options": '{"scenario":"conversation_tracks"}'},
            files={"file": ("mono.wav", wav(), "audio/wav")},
        )
        assert response.status_code == 422


def test_model_capacity_is_shared_across_requests_and_recipes() -> None:
    async def run() -> None:
        models = Models(
            Config(
                instances=[
                    Instance(model="qwen", url="http://a", capacity=2),
                    Instance(model="qwen", url="http://b", capacity=1),
                ]
            )
        )
        entered, peak = 0, 0
        release = asyncio.Event()
        ready = asyncio.Event()

        async def call() -> None:
            nonlocal entered, peak
            async with models.acquire("qwen"):
                entered += 1
                peak = max(peak, entered)
                if entered == 3:
                    ready.set()
                await release.wait()
                entered -= 1

        tasks = [asyncio.create_task(call()) for _ in range(5)]
        await asyncio.wait_for(ready.wait(), 1)
        assert sum(models.loads) == 3
        release.set()
        await asyncio.gather(*tasks)
        assert peak == 3
        assert models.loads == [0, 0]
        await models.http.aclose()

    asyncio.run(run())


def test_inference_uploads_audio_instead_of_shared_path(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(wav())
    body = b""

    async def run() -> None:
        def respond(request: httpx2.Request) -> httpx2.Response:
            nonlocal body
            body = request.read()
            assert request.url.path == "/align"
            return httpx2.Response(
                200,
                json={"text": "完成", "revision": "fixed", "parameters": {"mode": "verbatim"}},
                request=request,
            )

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
            models = Models(
                Config(instances=[Instance(model="qwen3-aligner", url="http://model")]), http
            )
            inference = Inference(models, tmp_path, Trace(), "narration/qwen")
            result = await inference.call(
                "qwen3-aligner", InferenceRequest(audio=str(audio), text="完成"), step="align"
            )
            assert result.revision == "fixed"
            assert inference.records

    asyncio.run(run())
    assert b"RIFF" in body
    assert str(tmp_path).encode() not in body
    assert b"\\u5b8c\\u6210" in body


def test_two_tracks_run_concurrently_without_diarization_and_keep_overlap(tmp_path: Path) -> None:
    audio = tmp_path / "stereo.wav"
    audio.write_bytes(wav(channels=2))
    work = tmp_path / "recipe"
    work.mkdir()
    started = set()
    ready = asyncio.Event()
    calls = []

    class FakeInference:
        def __init__(self) -> None:
            self.work = work
            self.models = type("Resources", (), {"cpu": asyncio.Semaphore(4)})()

        async def call(
            self, model: str, request: InferenceRequest, *, step: str, channel: str | None = None
        ) -> InferenceResult:
            calls.append(model)
            if model == "firered-vad":
                started.add(channel)
                if len(started) == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), 1)
                return InferenceResult(spans=[Span(start_ms=500, end_ms=1500)])
            if model == "qwen3-aligner":
                return InferenceResult(tokens=[Token(text=request.text, start_ms=300, end_ms=800)])
            if model == "firered-punc":
                return InferenceResult(text=request.text)
            with wave.open(request.audio, "rb") as clip:
                sample = array("h", clip.readframes(1))[0]
            return InferenceResult(text="左轨" if sample == 1000 else "右轨")

    result = asyncio.run(
        qwen.transcribe(FakeInference(), audio, 2000, Options(scenario="conversation_tracks"))
    )
    assert started == {"0", "1"}
    assert not any("diar" in model or "pyannote" in model for model in calls)
    assert [s.speakers for s in result.segments] == [["S01"], ["S02"]]
    assert [s.text for s in result.segments] == ["左轨", "右轨"]
    assert result.segments[0].start_ms == result.segments[1].start_ms == 500
    assert result.segments[0].end_ms > result.segments[1].start_ms


def test_joint_generation_starts_without_waiting_for_speaker_anchor(tmp_path: Path) -> None:
    from scheduler.scenarios.conversation import moss_joint

    generation = asyncio.Event()

    class FakeInference:
        def __init__(self) -> None:
            self.work = tmp_path
            self.models = type("Resources", (), {"cpu": asyncio.Semaphore(4)})()

        async def call(
            self, model: str, request: InferenceRequest, *, step: str
        ) -> InferenceResult:
            if model == "pyannote-community-1":
                await asyncio.wait_for(generation.wait(), 1)
                return InferenceResult(spans=[Span(start_ms=0, end_ms=2000, speaker="anchor")])
            if model == "firered-vad":
                return InferenceResult(spans=[Span(start_ms=0, end_ms=1000)])
            generation.set()
            return InferenceResult(
                spans=[Span(start_ms=0, end_ms=1000, speaker="local", text="你好")]
            )

    audio = tmp_path / "audio.wav"
    audio.write_bytes(wav())
    result = asyncio.run(
        moss_joint.transcribe(FakeInference(), audio, 2000, Options(scenario="conversation"))
    )
    assert result.segments[0].speakers == ["S01"]
    assert result.segments[0].text == "你好"
