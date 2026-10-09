import asyncio
import json
import wave
from pathlib import Path

import httpx2
import pytest

from models.vllm import (
    EventSourceContext,
    GenerationOptions,
    complete,
    complete_with_generation_retry,
)
from ops.scheduler import Scheduler
from protocol import InferenceRequest, InferenceResult
from server.config import read_config


@pytest.mark.parametrize("finish,done", [("length", True), ("stop", False)])
def test_partial_generation_is_never_accepted(finish: str, done: bool) -> None:
    event = {"choices": [{"delta": {"content": "只转了一半"}, "finish_reason": finish}]}
    payload = "data: " + json.dumps(event) + "\n\n"
    if done:
        payload += "data: [DONE]\n\n"

    async def run() -> None:
        def respond(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                text=payload,
                headers={"content-type": "text/event-stream"},
                request=request,
            )

        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client,
            client.sse("http://model") as source,
        ):
            await complete(source)

    with pytest.raises(ValueError, match="generation"):
        asyncio.run(run())


def test_vllm_stream_uses_standard_sse_framing() -> None:
    # 多行 data 字段是合法 SSE；协议库负责合并，业务层只解析完整事件。
    payload = (
        ": keep-alive\n"
        'data: {"choices": [{"delta":\n'
        'data: {"content": "完整"}, "finish_reason": "stop"}]}\n\n'
        "data: [DONE]\n\n"
    )

    async def run() -> str:
        def respond(request: httpx2.Request) -> httpx2.Response:
            return httpx2.Response(
                200,
                text=payload,
                headers={"content-type": "text/event-stream"},
                request=request,
            )

        async with (
            httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client,
            client.sse("http://model") as source,
        ):
            return (await complete(source)).text

    assert asyncio.run(run()) == "完整"


def test_vllm_retries_repetitive_generation_with_penalty() -> None:
    attempts: list[GenerationOptions] = []

    async def run() -> InferenceResult:
        def respond(request: httpx2.Request) -> httpx2.Response:
            penalty = float(request.url.params.get("repetition_penalty", "1"))
            text = "完整" if penalty == 1.3 else "对" * 64
            finish = "stop" if penalty == 1.3 else None
            event = {"choices": [{"delta": {"content": text}, "finish_reason": finish}]}
            payload = "data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n"
            return httpx2.Response(
                200,
                text=payload,
                headers={"content-type": "text/event-stream"},
                request=request,
            )

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:

            def source(options: GenerationOptions) -> EventSourceContext:
                attempts.append(options)
                return client.sse("http://model", params=options)

            return await complete_with_generation_retry(source)

    result = asyncio.run(run())
    assert result.text == "完整"
    assert result.warnings == ["repetitive_generation_retry:1.3"]
    assert isinstance(result.raw, dict)
    assert result.raw["repetition_penalty"] == 1.3
    assert attempts == [
        {},
        {"repetition_penalty": 1.1},
        {"repetition_penalty": 1.2},
        {"repetition_penalty": 1.3},
    ]


def test_vllm_retries_generation_limit_with_sampling() -> None:
    attempts: list[GenerationOptions] = []

    async def run() -> InferenceResult:
        def respond(request: httpx2.Request) -> httpx2.Response:
            sampled = request.url.params.get("temperature") == "0.5"
            event = {
                "choices": [
                    {
                        "delta": {"content": "完整" if sampled else "异常长输出"},
                        "finish_reason": "stop" if sampled else "length",
                    }
                ]
            }
            payload = "data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n"
            return httpx2.Response(
                200,
                text=payload,
                headers={"content-type": "text/event-stream"},
                request=request,
            )

        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:

            def source(options: GenerationOptions) -> EventSourceContext:
                attempts.append(options)
                return client.sse("http://model", params=options)

            return await complete_with_generation_retry(source)

    result = asyncio.run(run())
    assert result.text == "完整"
    assert result.warnings == ["generation_length_retry:sampling"]
    assert isinstance(result.raw, dict)
    assert result.raw["temperature"] == 0.5
    assert result.raw["top_p"] == 0.9
    assert result.raw["seed"] == 2
    assert attempts == [{}, {"temperature": 0.5, "top_p": 0.9, "seed": 2}]


def test_vibevoice_uses_upstream_transcription_request(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 16000)
    payload = None
    event = {
        "choices": [
            {
                "delta": {
                    "content": (
                        'assistant\n[{"Start":0,"End":1,"Speaker":0,"Content":"测试"},'
                        '{"Start":1,"End":2,"Content":"[Silence]"}]'
                    )
                },
                "finish_reason": "stop",
            }
        ]
    }

    def respond(request: httpx2.Request) -> httpx2.Response:
        nonlocal payload
        payload = json.loads(request.content)
        content = "data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n"
        return httpx2.Response(
            200,
            text=content,
            headers={"content-type": "text/event-stream"},
            request=request,
        )

    async def run() -> None:
        scheduler = Scheduler(
            read_config(Path(__file__).resolve().parents[1] / "server/server.yaml")
        )
        try:
            async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as client:
                instance = scheduler.instances["vibevoice-a"]
                result = await instance.client(
                    client,
                    instance.url,
                    InferenceRequest(audio=str(audio), hotwords=["测试词"]),
                )
            assert result.text.endswith('"Content":"[Silence]"}]')
            assert len(result.spans) == 1
            assert result.spans[0].speaker == "0"
        finally:
            await scheduler.close()

    asyncio.run(run())
    assert payload is not None
    assert payload["max_tokens"] == 32768
    assert payload["temperature"] == 0
    assert payload["top_p"] == 1
    assert payload["chat_template_kwargs"] == {"audio_duration": "1.00"}
    assert payload["messages"][0]["content"][0]["type"] == "audio_url"
    assert payload["messages"][0]["content"][0]["audio_url"]["url"].startswith(
        "data:audio/wav;base64,"
    )
    assert payload["messages"][0]["content"][1] == {"type": "text", "text": "测试词"}
