import collections
import sys
from collections.abc import Callable
from typing import Any

from transformers.models.qwen2 import modeling_qwen2


def register_wrapped_qwen2_for_aot_pickle() -> None:
    """Give decorated Qwen2 forward functions stable AOT serialization names."""
    function: Callable[..., Any] = modeling_qwen2.Qwen2Model.forward
    depth = 0
    while True:
        function.__globals__["collections"] = collections
        if not (wrapped := getattr(function, "__wrapped__", None)):
            break
        function = wrapped
        depth += 1
        name = f"_vllm_aot_qwen2_model_forward_{depth}"
        function.__name__ = name
        function.__qualname__ = name
        setattr(modeling_qwen2, name, function)


register_wrapped_qwen2_for_aot_pickle()


def main() -> None:
    sys.argv.insert(1, "serve")
    from vllm.entrypoints.cli.main import main as vllm_main

    vllm_main()


if __name__ == "__main__":
    main()
