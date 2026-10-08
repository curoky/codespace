import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from pydantic import JsonValue

from ops.scheduler import Scheduler
from server.audio import decode
from server.config import Config
from server.inference import Inference
from server.recipes import RECIPE_IDS, Options, Pipeline
from server.tracing import Trace
from server.transcript import Transcript


async def transcribe(
    source: Path,
    work: Path,
    config: Config,
    scheduler: Scheduler,
    options: Options,
    trace: Trace,
) -> tuple[list[Transcript], dict[str, JsonValue]]:
    started = trace.begin()
    try:
        async with scheduler.cpu:
            audio, duration, metadata = await decode(source, work)
    except Exception as exc:
        trace.add(
            kind="phase",
            name="decode",
            channel="mono",
            started=started,
            status="failed",
            input_summary={"source_bytes": source.stat().st_size},
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    trace.add(
        kind="phase",
        name="decode",
        channel="mono",
        started=started,
        status="completed",
        input_summary={"source_bytes": source.stat().st_size},
        output_summary={"audio_bytes": audio.stat().st_size, "duration_ms": duration},
    )
    channels: list[int | None] = [None]
    if options.separate_channels:
        streams = json.loads(metadata)["streams"]
        channels = list(range(next(s["channels"] for s in streams if s["codec_type"] == "audio")))
    combined = {recipe: Transcript(recipe=recipe) for recipe in RECIPE_IDS}
    evidence: dict[str, JsonValue] = {}
    for channel in channels:
        channel_work = work if channel is None else work / f"channel-{channel}"
        channel_work.mkdir(exist_ok=True)
        if channel is not None:
            started = trace.begin()
            try:
                async with scheduler.cpu:
                    audio, duration, _ = await decode(source, channel_work, channel=channel)
            except Exception as exc:
                trace.add(
                    kind="phase",
                    name="decode",
                    channel=str(channel),
                    started=started,
                    status="failed",
                    input_summary={"source_bytes": source.stat().st_size},
                    error=f"{type(exc).__name__}: {exc}",
                )
                raise
            trace.add(
                kind="phase",
                name="decode",
                channel=str(channel),
                started=started,
                status="completed",
                input_summary={"source_bytes": source.stat().st_size},
                output_summary={"audio_bytes": audio.stat().st_size, "duration_ms": duration},
            )
        channel_name = "mono" if channel is None else str(channel)
        inference = Inference(scheduler, channel_work, trace, channel_name)
        pipeline = Pipeline(config, inference, audio, duration, options)
        outputs = await run_recipes(pipeline)
        evidence["mono" if channel is None else str(channel)] = pipeline.evidence()
        for output in outputs:
            result = output.model_copy(deep=True)
            if channel is not None:
                for segment in result.segments:
                    segment.channel = channel
                    segment.speakers = [f"C{channel + 1}-{s}" for s in segment.speakers]
                    for token in segment.tokens:
                        token.speakers = [f"C{channel + 1}-{s}" for s in token.speakers]
                for speaker in result.speakers:
                    if speaker.speaker:
                        speaker.speaker = f"C{channel + 1}-{speaker.speaker}"
            target = combined[result.recipe]
            target.segments.extend(result.segments)
            target.speakers.extend(result.speakers)
            target.activity.extend(result.activity)
            target.warnings.extend(result.warnings)
            if result.status != "completed":
                target.status = "failed"
                target.error = (target.error or "") + f"channel={channel}: {result.error}; "
    for result in combined.values():
        result.segments.sort(key=lambda s: (s.start_ms, s.channel or 0))
    return list(combined.values()), evidence


async def run_recipes(pipeline: Pipeline) -> list[Transcript]:
    async def phase(
        name: str,
        operation: Awaitable[None],
        summary: Callable[[], dict[str, JsonValue]],
    ) -> None:
        started = pipeline.inference.trace.begin()
        try:
            await operation
        except Exception as exc:
            pipeline.inference.trace.add(
                kind="phase",
                name=name,
                channel=pipeline.inference.channel,
                started=started,
                status="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        pipeline.inference.trace.add(
            kind="phase",
            name=name,
            channel=pipeline.inference.channel,
            started=started,
            status="completed",
            output_summary=summary(),
        )

    await phase(
        "prepare",
        pipeline.prepare(),
        lambda: {
            "activity_spans": len(pipeline.activity),
            "speaker_spans": len(pipeline.speakers),
            "windows": len(pipeline.chunks),
        },
    )
    await phase(
        "first_pass",
        pipeline.first_pass(),
        lambda: {
            "windows": len(pipeline.chunks),
            "candidate_results": sum(len(items) for items in pipeline.candidates.values()),
            "errors": sum(key.startswith("first_pass:") for key in pipeline.errors),
        },
    )
    await phase(
        "review",
        pipeline.review(),
        lambda: {
            "disputed_windows": len(pipeline.reviewed),
            "review_results": sum(len(items) for items in pipeline.reviewed.values()),
            "errors": sum(key.startswith("review:") for key in pipeline.errors),
        },
    )

    async def execute(recipe: str, operation: Awaitable[Transcript]) -> Transcript:
        logging.info("transcribing %s: %s", pipeline.audio, recipe)
        started = pipeline.inference.trace.begin()
        try:
            result = await operation
        except Exception as exc:
            # 一份方案的模型故障不会抹掉其他模型已取得的转录证据。
            logging.exception("recipe %s failed", recipe)
            result = Transcript(recipe=recipe, status="failed", error=str(exc))
        pipeline.inference.trace.add(
            kind="phase",
            name="recipe." + recipe,
            channel=pipeline.inference.channel,
            started=started,
            status="completed" if result.status == "completed" else "failed",
            output_summary={
                "segments": len(result.segments),
                "warnings": len(result.warnings),
            },
            error=result.error,
        )
        return result

    qwen = await execute(RECIPE_IDS[0], pipeline.fusion(RECIPE_IDS[0], "qwen3-asr-1.7b"))
    firered = await execute(RECIPE_IDS[1], pipeline.fusion(RECIPE_IDS[1], "firered-llm"))
    moss = await execute(RECIPE_IDS[2], pipeline.joint(RECIPE_IDS[2], "moss-td"))
    vibevoice = await execute(RECIPE_IDS[3], pipeline.joint(RECIPE_IDS[3], "vibevoice"))
    if qwen.status == "completed":
        nemotron = await execute(RECIPE_IDS[4], pipeline.nemotron(qwen))
    else:
        started = pipeline.inference.trace.begin()
        nemotron = Transcript(recipe=RECIPE_IDS[4], status="failed", error="01 did not complete")
        pipeline.inference.trace.add(
            kind="phase",
            name="recipe." + RECIPE_IDS[4],
            channel=pipeline.inference.channel,
            started=started,
            status="failed",
            output_summary={"segments": 0, "warnings": 0},
            error=nemotron.error,
        )
    return [qwen, firered, moss, vibevoice, nemotron]
