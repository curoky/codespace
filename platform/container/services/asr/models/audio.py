import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import UploadFile

from protocol import InferenceRequest, InferenceResult


@contextmanager
def uploaded(file: UploadFile | None, options: str) -> Iterator[InferenceRequest]:
    request = InferenceRequest.model_validate_json(options)
    with tempfile.TemporaryDirectory(prefix="inference-", dir="/data/asr") as temporary:
        if file is not None:
            path = Path(temporary) / "audio.wav"
            with path.open("wb") as target:
                while chunk := file.file.read(1024 * 1024):
                    target.write(chunk)
            request.audio = str(path)
        yield request


def evidence(
    result: InferenceResult, request: InferenceRequest, model_dir: Path
) -> InferenceResult:
    result.revision = (model_dir / "weights/.revision").read_text().strip()
    result.parameters = request.model_dump(mode="json", exclude={"audio"})
    return result
