import asyncio
import json
import logging
from collections.abc import Awaitable
from pathlib import Path

from pydantic import Field, JsonValue

from ops.scheduler import Scheduler
from protocol import Record
from server import artifacts
from server.audio import decode
from server.config import Config
from server.inference import Inference
from server.recipes import RECIPE_IDS, Options, Pipeline
from server.storage import atomic_text, digest, file_hash
from server.transcript import Transcript


class Status(Record):
    id: str
    state: str = "queued"
    stage: str = "queued"
    recipes: dict[str, str] = Field(default_factory=lambda: dict.fromkeys(RECIPE_IDS, "queued"))
    error: str | None = None


class Resolved(Record):
    filename: str
    input_sha256: str
    options: Options
    deployment: str
    models: dict[str, JsonValue]
    config: dict[str, JsonValue]


class Jobs:
    def __init__(self, config: Config, scheduler: Scheduler) -> None:
        self.config, self.scheduler = config, scheduler
        self.root = config.data_dir / "jobs"
        self.root.mkdir(parents=True, exist_ok=True)
        files = sorted(Path(__file__).parent.glob("*.py"))
        self.deployment = digest(
            {
                "config": config.model_dump(mode="json"),
                "models": {key: value.fingerprint for key, value in scheduler.instances.items()},
                "code": {path.name: file_hash(path) for path in files},
            }
        )
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.workers: list[asyncio.Task[None]] = []

    def status(self, job: str) -> Status:
        return Status.model_validate_json((self.root / job / "status.json").read_text())

    def update(self, status: Status) -> None:
        atomic_text(self.root / status.id / "status.json", status.model_dump_json(indent=2))

    async def start(self) -> None:
        for directory in sorted(self.root.iterdir()):
            if directory.name.startswith(".") or not (directory / "status.json").is_file():
                continue
            status = self.status(directory.name)
            if status.state in ("queued", "running"):
                await self.queue.put(status.id)
        self.workers = [
            asyncio.create_task(self.worker()) for _ in range(self.config.parallel.active_files)
        ]

    async def close(self) -> None:
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)

    async def worker(self) -> None:
        while True:
            job = await self.queue.get()
            try:
                await self.run(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logging.exception("job %s failed", job)
                status = self.status(job)
                status.state, status.stage, status.error = "failed", "failed", str(exc)
                directory = self.root / job / "artifacts"
                for recipe, state in status.recipes.items():
                    if state != "completed":
                        artifacts.save(
                            directory, Transcript(recipe=recipe, status="failed", error=str(exc))
                        )
                        status.recipes[recipe] = "failed"
                artifacts.index(directory, status.recipes)
                artifacts.bundle(directory)
                self.update(status)
            finally:
                self.queue.task_done()

    async def run(self, job: str) -> None:
        directory = self.root / job
        resolved = Resolved.model_validate_json((directory / "resolved.json").read_text())
        if resolved.deployment != self.deployment:
            raise ValueError(
                "deployment changed; submit a new job rather than reusing stale results"
            )
        status = self.status(job)
        status.state, status.stage = "running", "decode"
        self.update(status)
        work = directory / "work"
        work.mkdir(exist_ok=True)
        async with self.scheduler.cpu:
            audio, duration, metadata = await decode(directory / "input" / "original", work)
        atomic_text(work / "audio-metadata.json", metadata)
        channels: list[int | None] = [None]
        if resolved.options.separate_channels:
            streams = json.loads(metadata)["streams"]
            count = next(s["channels"] for s in streams if s["codec_type"] == "audio")
            channels = list(range(count))
        combined = {recipe: Transcript(recipe=recipe) for recipe in RECIPE_IDS}
        for channel in channels:
            channel_work = work if channel is None else work / f"channel-{channel}"
            channel_work.mkdir(exist_ok=True)
            try:
                if channel is not None:
                    audio, duration, _ = await decode(
                        directory / "input" / "original", channel_work, channel=channel
                    )
                outputs = await self.transcribe(
                    job, resolved, status, channel_work, audio, duration
                )
            except Exception as exc:
                logging.exception("job %s channel %s failed", job, channel)
                outputs = {
                    recipe: Transcript(recipe=recipe, status="failed", error=str(exc))
                    for recipe in RECIPE_IDS
                }
            for recipe, result in outputs.items():
                if channel is not None:
                    for segment in result.segments:
                        segment.channel = channel
                        segment.speakers = [f"C{channel + 1}-{s}" for s in segment.speakers]
                        for token in segment.tokens:
                            token.speakers = [f"C{channel + 1}-{s}" for s in token.speakers]
                    for speaker in result.speakers:
                        if speaker.speaker:
                            speaker.speaker = f"C{channel + 1}-{speaker.speaker}"
                target = combined[recipe]
                target.segments.extend(result.segments)
                target.speakers.extend(result.speakers)
                target.activity.extend(result.activity)
                target.warnings.extend(result.warnings)
                target.evidence[str(channel)] = result.evidence
                target.provenance = resolved.model_dump(mode="json")
                if result.status != "completed":
                    target.status = "failed"
                    target.error = (target.error or "") + f"channel={channel}: {result.error}; "
        for recipe, result in combined.items():
            result.segments.sort(key=lambda s: (s.start_ms, s.channel or 0))
            artifacts.save(directory / "artifacts", result)
            status.recipes[recipe] = result.status
        artifacts.index(directory / "artifacts", status.recipes)
        completed = sum(state == "completed" for state in status.recipes.values())
        status.state = (
            "completed" if completed == 5 else ("partial_failed" if completed else "failed")
        )
        status.stage = "finished"
        await asyncio.to_thread(artifacts.bundle, directory / "artifacts")
        self.update(status)

    async def transcribe(
        self, job: str, resolved: Resolved, status: Status, work: Path, audio: Path, duration: int
    ) -> dict[str, Transcript]:
        results: dict[str, Transcript] = {}
        inference = Inference(self.scheduler, work)
        pipeline = Pipeline(self.config, inference, audio, duration, resolved.options)
        status.stage = "activity_and_speakers"
        self.update(status)
        await pipeline.prepare()
        status.stage = "independent_recognition"
        self.update(status)
        await pipeline.first_pass()

        async def execute(recipe: str, operation: Awaitable[Transcript]) -> Transcript:
            status.stage = recipe
            status.recipes[recipe] = "running"
            self.update(status)
            try:
                result = await operation
            except Exception as exc:
                logging.exception("job %s recipe %s failed", job, recipe)
                result = Transcript(recipe=recipe, status="failed", error=str(exc))
            result.evidence = pipeline.evidence()
            result.provenance = resolved.model_dump(mode="json")
            results[recipe] = result
            status.recipes[recipe] = result.status
            self.update(status)
            return result

        async def fusion(recipe: str, primary: str) -> Transcript:
            return await pipeline.fusion(recipe, primary)

        qwen = await execute(RECIPE_IDS[0], fusion(RECIPE_IDS[0], "qwen3-asr-1.7b"))
        await execute(RECIPE_IDS[1], fusion(RECIPE_IDS[1], "firered-llm"))
        await execute(RECIPE_IDS[2], pipeline.joint(RECIPE_IDS[2], "moss-td"))
        await execute(RECIPE_IDS[3], pipeline.joint(RECIPE_IDS[3], "vibevoice"))

        async def nemotron() -> Transcript:
            if qwen.status != "completed":
                raise RuntimeError("01-qwen-fusion did not complete")
            return await pipeline.nemotron(qwen)

        await execute(RECIPE_IDS[4], nemotron())
        return results
