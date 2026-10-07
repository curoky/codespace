import asyncio
import json

import httpx
import pytest

from models.vllm import complete


@pytest.mark.parametrize("finish,done", [("length", True), ("stop", False)])
def test_partial_generation_is_never_accepted(finish: str, done: bool) -> None:
    event = {"choices": [{"delta": {"content": "只转了一半"}, "finish_reason": finish}]}
    payload = "data: " + json.dumps(event) + "\n\n"
    if done:
        payload += "data: [DONE]\n\n"
    response = httpx.Response(200, text=payload, request=httpx.Request("POST", "http://model"))
    with pytest.raises(ValueError, match="incomplete generation"):
        asyncio.run(complete(response))
