# /// script
# requires-python = ">=3.12"
# dependencies = ["PyYAML==6.0.3"]
# ///
import argparse
import asyncio
from pathlib import Path

import yaml


async def run(server: str, scenario: str | None) -> None:
    root = Path(__file__).resolve().parent
    manifest = yaml.safe_load((root / "manifest.yaml").read_text())
    limit = asyncio.Semaphore(2)

    async def fixture(entry: dict[str, object]) -> None:
        async with limit:
            audio = entry["audio"]
            speakers = entry["speakers"]
            if not isinstance(audio, dict) or not isinstance(speakers, dict):
                raise ValueError(f"invalid regression fixture: {entry['id']}")
            command = [
                "uv",
                "run",
                str(root.parent / "client/asr.py"),
                str(root / str(audio["path"])),
                "--scenario",
                str(entry["category"]),
                "--num-speakers",
                str(speakers["count"]),
                "--server",
                server,
                "--out",
                str(root / str(entry["category"]) / "results"),
                "--overwrite",
            ]
            recipes = entry["recipes"]
            if not isinstance(recipes, list):
                raise ValueError(f"invalid regression recipes: {entry['id']}")
            for name in recipes:
                command.extend(["--recipe", str(name)])
            process = await asyncio.create_subprocess_exec(*command)
            try:
                if await process.wait():
                    raise RuntimeError(f"regression failed: {entry['id']}")
            finally:
                if process.returncode is None:
                    process.terminate()
                    await process.wait()

    async with asyncio.TaskGroup() as tasks:
        for entry in manifest["fixtures"]:
            if scenario is None or entry["category"] == scenario:
                tasks.create_task(fixture(entry))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="http://127.0.0.1:18080")
    parser.add_argument(
        "--scenario", choices=["conversation", "meeting", "narration", "conversation_tracks"]
    )
    args = parser.parse_args()
    asyncio.run(run(args.server, args.scenario))


if __name__ == "__main__":
    main()
