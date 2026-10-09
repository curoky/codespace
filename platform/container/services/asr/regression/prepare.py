# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx==0.28.1", "PyYAML==6.0.3"]
# ///
import argparse
import hashlib
import shutil
import sys
import tarfile
import tempfile
import wave
from array import array
from collections import defaultdict
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "manifest.yaml"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify(path: Path, expected_size: int, expected_sha256: str) -> str | None:
    if not path.is_file():
        return "missing"
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        return f"size {actual_size} != {expected_size}"
    actual_sha256 = sha256(path)
    if actual_sha256 != expected_sha256:
        return f"sha256 {actual_sha256} != {expected_sha256}"
    return None


def download(source: dict[str, object], destination: Path) -> None:
    url = str(source["url"])
    expected_size = int(source["size_bytes"])
    if not url.startswith("https://"):
        raise ValueError(f"only HTTPS downloads are allowed: {url}")
    received = 0
    next_report = 64 * 1024 * 1024
    print(f"下载 {url}")
    with (
        httpx.stream(
            "GET",
            url,
            follow_redirects=True,
            headers={"User-Agent": "codespace-asr-regression/1"},
            timeout=httpx.Timeout(1800),
        ) as response,
        destination.open("wb") as output,
    ):
        response.raise_for_status()
        for chunk in response.iter_bytes(8 * 1024 * 1024):
            output.write(chunk)
            received += len(chunk)
            if received >= next_report:
                print(f"  {received / 1024 / 1024:.0f} / {expected_size / 1024 / 1024:.0f} MiB")
                next_report += 64 * 1024 * 1024
    error = verify(destination, expected_size, str(source["sha256"]))
    if error is not None:
        raise ValueError(f"download verification failed for {url}: {error}")


def extract_member(archive: Path, member_name: str, destination: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.getmember(member_name)
        if not member.isfile():
            raise ValueError(f"archive member is not a file: {member_name}")
        source = tar.extractfile(member)
        if source is None:
            raise ValueError(f"cannot read archive member: {member_name}")
        with source, destination.open("wb") as output:
            shutil.copyfileobj(source, output)


def first_channel_pcm(source: Path, destination: Path, duration_seconds: int) -> None:
    with wave.open(str(source), "rb") as input_audio:
        channels = input_audio.getnchannels()
        sample_width = input_audio.getsampwidth()
        frame_rate = input_audio.getframerate()
        if channels < 2 or sample_width != 2:
            raise ValueError("first_channel_pcm requires multi-channel 16-bit PCM WAV")
        remaining = duration_seconds * frame_rate
        with wave.open(str(destination), "wb") as output_audio:
            output_audio.setnchannels(1)
            output_audio.setsampwidth(sample_width)
            output_audio.setframerate(frame_rate)
            while remaining:
                frames = min(remaining, frame_rate * 10)
                payload = input_audio.readframes(frames)
                if not payload:
                    raise ValueError("source audio ended before requested duration")
                samples = array("h")
                samples.frombytes(payload)
                if sys.byteorder == "big":
                    samples.byteswap()
                mono = array("h", samples[::channels])
                if sys.byteorder == "big":
                    mono.byteswap()
                output_audio.writeframesraw(mono.tobytes())
                remaining -= len(samples) // channels


def materialize(fixture: dict[str, object], source_path: Path, temporary: Path) -> None:
    audio = fixture["audio"]
    if not isinstance(audio, dict):
        raise ValueError(f"invalid audio entry for {fixture['id']}")
    destination = ROOT / str(audio["path"])
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate = destination.with_name(f".{destination.name}.partial")
    candidate.unlink(missing_ok=True)

    source_member = fixture.get("source_member")
    transform = fixture.get("transform")
    if source_member is not None:
        extracted = temporary / destination.name
        extract_member(source_path, str(source_member), extracted)
        input_path = extracted
    else:
        input_path = source_path

    if transform is None:
        shutil.copyfile(input_path, candidate)
    else:
        if not isinstance(transform, dict):
            raise ValueError(f"invalid transform for {fixture['id']}")
        if transform.get("kind") != "first_channel_pcm":
            raise ValueError(f"unsupported transform for {fixture['id']}: {transform}")
        first_channel_pcm(input_path, candidate, int(transform["duration_seconds"]))

    error = verify(candidate, int(audio["size_bytes"]), str(audio["sha256"]))
    if error is not None:
        candidate.unlink(missing_ok=True)
        raise ValueError(f"output verification failed for {fixture['id']}: {error}")
    candidate.replace(destination)
    print(f"完成 {fixture['id']} → {destination.relative_to(ROOT)}")


def load_manifest() -> dict[str, object]:
    payload = yaml.safe_load(MANIFEST.read_text())
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported regression manifest")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixtures", nargs="*")
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest()
    fixtures = manifest["fixtures"]
    sources = manifest["sources"]
    if not isinstance(fixtures, list) or not isinstance(sources, dict):
        raise ValueError("manifest fixtures and sources must be collections")
    selected = [
        fixture
        for fixture in fixtures
        if (not args.fixtures or fixture["id"] in args.fixtures)
        and (not args.category or fixture["category"] in args.category)
    ]
    if len(selected) != len(args.fixtures) and args.fixtures:
        known = {fixture["id"] for fixture in selected}
        missing = sorted(set(args.fixtures) - known)
        raise ValueError(f"unknown fixtures: {', '.join(missing)}")

    pending: dict[str, list[dict[str, object]]] = defaultdict(list)
    failures = []
    for fixture in selected:
        audio = fixture["audio"]
        if not isinstance(audio, dict):
            raise ValueError(f"invalid audio entry for {fixture['id']}")
        destination = ROOT / str(audio["path"])
        error = verify(destination, int(audio["size_bytes"]), str(audio["sha256"]))
        if error is None:
            print(f"有效 {fixture['id']} → {destination.relative_to(ROOT)}")
            continue
        if args.check:
            failures.append(f"{fixture['id']}: {error}")
            continue
        if destination.exists() and not args.overwrite:
            raise ValueError(f"{destination} failed verification ({error}); use --overwrite")
        pending[str(fixture["source"])].append(fixture)

    if failures:
        raise ValueError("audio cache check failed:\n" + "\n".join(failures))
    if args.check:
        return

    for source_id, source_fixtures in pending.items():
        source = sources[source_id]
        if not isinstance(source, dict):
            raise ValueError(f"invalid source entry: {source_id}")
        with tempfile.TemporaryDirectory(prefix="asr-regression-") as directory:
            temporary = Path(directory)
            source_path = temporary / "source"
            download(source, source_path)
            for fixture in source_fixtures:
                materialize(fixture, source_path, temporary)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, tarfile.TarError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc
