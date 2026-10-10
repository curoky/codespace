from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import httpx2
from pydantic import ConfigDict, Field, JsonValue

from protocol import InferenceResult, Record

type EventSourceContext = AbstractAsyncContextManager[httpx2.EventSource]
type GenerationOptions = dict[str, float | int]


class Delta(Record):
    model_config = ConfigDict(extra="ignore")
    content: str | None = None


class Choice(Record):
    model_config = ConfigDict(extra="ignore")
    delta: Delta = Field(default_factory=Delta)
    finish_reason: str | None = None


class Event(Record):
    model_config = ConfigDict(extra="ignore")
    choices: list[Choice] = Field(default_factory=list)


class RepetitiveGenerationError(ValueError):
    pass


class GenerationLimitError(ValueError):
    pass


def repetitive_suffix(text: str) -> bool:
    """识别生成尾部已经进入的短周期循环。"""
    for width in range(1, 9):
        repetitions = max(8, (64 + width - 1) // width)
        repeated = text[-width:] * repetitions
        if len(text) >= len(repeated) and text.endswith(repeated):
            return True
    return False


async def complete(source: httpx2.EventSource) -> InferenceResult:
    """聚合 vLLM 的标准 SSE 流，只接受显式完成且未被截断的生成。"""
    source.response.raise_for_status()
    text = ""
    finishes = []
    ended = False
    async for message in source:
        if message.data == "[DONE]":
            ended = True
            break
        event = Event.model_validate_json(message.data)
        for choice in event.choices:
            if choice.delta.content:
                text += choice.delta.content
                if repetitive_suffix(text):
                    raise RepetitiveGenerationError("repetitive generation")
            if choice.finish_reason:
                finishes.append(choice.finish_reason)
    if ended and finishes and all(reason == "length" for reason in finishes):
        raise GenerationLimitError(f"generation limit reached ({finishes})")
    if not ended or not finishes or any(reason != "stop" for reason in finishes):
        raise ValueError(f"incomplete generation ({finishes})")
    return InferenceResult(
        text=text, raw={"text": text, "finish_reasons": list[JsonValue](finishes)}
    )


def with_retry_metadata(
    result: InferenceResult, options: GenerationOptions, warning: str
) -> InferenceResult:
    raw = result.raw if isinstance(result.raw, dict) else {"response": result.raw}
    return result.model_copy(
        update={
            "raw": {**raw, **options},
            "warnings": [warning],
        }
    )


async def complete_with_generation_retry(
    source_factory: Callable[[GenerationOptions], EventSourceContext],
) -> InferenceResult:
    """保留正常贪心输出，按失败类型选择确定性的异常生成重试。"""
    try:
        async with source_factory({}) as source:
            return await complete(source)
    except RepetitiveGenerationError:
        pass
    except GenerationLimitError:
        return await complete_with_sampling_retry(
            source_factory, "generation_length_retry:sampling"
        )

    for penalty in (1.1, 1.2, 1.3):
        try:
            options: GenerationOptions = {"repetition_penalty": penalty}
            async with source_factory(options) as source:
                result = await complete(source)
            return with_retry_metadata(result, options, f"repetitive_generation_retry:{penalty}")
        except RepetitiveGenerationError:
            if penalty == 1.3:
                return await complete_with_sampling_retry(
                    source_factory, "repetitive_generation_retry:sampling"
                )
        except GenerationLimitError:
            return await complete_with_sampling_retry(
                source_factory, "generation_length_retry:sampling"
            )
    raise AssertionError("unreachable")


async def complete_with_sampling_retry(
    source_factory: Callable[[GenerationOptions], EventSourceContext],
    warning: str,
) -> InferenceResult:
    options: GenerationOptions = {"temperature": 0.5, "top_p": 0.9, "seed": 2}
    async with source_factory(options) as source:
        result = await complete(source)
    return with_retry_metadata(result, options, warning)
