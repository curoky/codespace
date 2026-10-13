import threading
import unicodedata
from pathlib import Path

from fastapi import FastAPI, Form, UploadFile

from models.audio import evidence, uploaded
from protocol import InferenceResult


def preserve_content(source: str, punctuated: str) -> str:
    characters = [
        char
        for char in source
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    ]
    numeric_separators: dict[int, str] = {}
    position = 0
    for offset, char in enumerate(source):
        if not char.isspace() and not unicodedata.category(char).startswith("P"):
            position += 1
        elif (
            char in ".,，:："
            and offset
            and offset + 1 < len(source)
            and source[offset - 1].isdigit()
            and source[offset + 1].isdigit()
        ):
            numeric_separators[position] = char
    output = []
    index = 0
    for char in punctuated:
        if unicodedata.category(char).startswith("P"):
            if index not in numeric_separators:
                output.append(char)
        elif not char.isspace():
            if index >= len(characters) or char.lower() != characters[index].lower():
                raise ValueError(
                    f"punctuation model changed transcript content: {source!r} -> {punctuated!r}"
                )
            output.append(characters[index])
            index += 1
            if index in numeric_separators:
                output.append(numeric_separators[index])
        elif index and index < len(characters):
            output.append(char)
    if index != len(characters):
        raise ValueError(
            f"punctuation model omitted transcript content: {source!r} -> {punctuated!r}"
        )
    return "".join(output)


def app() -> FastAPI:
    from fireredasr2s.fireredpunc.punc import FireRedPunc, FireRedPuncConfig

    weights = Path(__file__).resolve().parent / "weights"
    # 标点使用 CPU；上层按语音窗口调用，并拒绝任何非标点字符的改写。
    model = FireRedPunc.from_pretrained(str(weights), FireRedPuncConfig(use_gpu=False))
    service = FastAPI(docs_url=None, redoc_url=None)
    lock = threading.Lock()

    @service.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @service.post("/punctuate")
    def punctuate(file: UploadFile | None = None, options: str = Form("{}")) -> InferenceResult:
        with uploaded(file, options) as request, lock:
            result = model.process([request.text])[0]
            warnings = []
            try:
                text = preserve_content(request.text, result["punc_text"])
            except ValueError:
                text = request.text
                warnings.append("punctuation_changed_content_rejected")
            result_record = InferenceResult(text=text, raw=result, warnings=warnings)
            return evidence(result_record, request, Path(__file__).resolve().parent)

    return service
