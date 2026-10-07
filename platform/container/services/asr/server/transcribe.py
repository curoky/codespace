import json
import logging
from collections.abc import Awaitable
from pathlib import Path

from pydantic import JsonValue

from ops.scheduler import Scheduler
from server.audio import decode
from server.config import Config
from server.inference import Inference
from server.recipes import RECIPE_IDS, Options, Pipeline
from server.transcript import Transcript


async def transcribe(
    source: Path, work: Path, config: Config, scheduler: Scheduler, options: Options
) -> tuple[list[Transcript], dict[str, JsonValue]]:
    async with scheduler.cpu:
        audio, duration, metadata = await decode(source, work)
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
            async with scheduler.cpu:
                audio, duration, _ = await decode(source, channel_work, channel=channel)
        inference = Inference(scheduler, channel_work)
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
    await pipeline.prepare()
    await pipeline.first_pass()
    await pipeline.review()

    async def execute(recipe: str, operation: Awaitable[Transcript]) -> Transcript:
        logging.info("transcribing %s: %s", pipeline.audio, recipe)
        try:
            return await operation
        except Exception as exc:
            # 一份方案的模型故障不会抹掉其他模型已取得的转录证据。
            logging.exception("recipe %s failed", recipe)
            return Transcript(recipe=recipe, status="failed", error=str(exc))

    qwen = await execute(RECIPE_IDS[0], pipeline.fusion(RECIPE_IDS[0], "qwen3-asr-1.7b"))
    firered = await execute(RECIPE_IDS[1], pipeline.fusion(RECIPE_IDS[1], "firered-llm"))
    moss = await execute(RECIPE_IDS[2], pipeline.joint(RECIPE_IDS[2], "moss-td"))
    vibevoice = await execute(RECIPE_IDS[3], pipeline.joint(RECIPE_IDS[3], "vibevoice"))
    if qwen.status == "completed":
        nemotron = await execute(RECIPE_IDS[4], pipeline.nemotron(qwen))
    else:
        nemotron = Transcript(recipe=RECIPE_IDS[4], status="failed", error="01 did not complete")
    return [qwen, firered, moss, vibevoice, nemotron]
