#!/usr/bin/env bash

# SGLang entrypoint for the host-level Qwen3.8-Flash-Next-FP8 serving image. Reads
# knobs from the container environment and launches an OpenAI-compatible server.
# Model weights are never baked in: the ~172 GiB FP8 weights are resolved from a
# bind-mounted Hugging Face cache (HF_HOME) and pulled on first start.
#
# Environment knobs (defaults tuned for a single 8x H100 node):
#   LLM_MODEL        model id or local path (default Qwen/Qwen3.8-Flash-Next-FP8)
#   LLM_HOST         bind address inside the container (default 0.0.0.0)
#   LLM_PORT         OpenAI API port inside the container (default 8003)
#   TP_SIZE          tensor-parallel size (default 8, matches 8x H100)
#   EP_SIZE          expert-parallel size (default 8, TEP8 for the MoE layout)
#   MAX_MODEL_LEN    context window (default 262144, the native length)
#   GPU_MEM_UTIL     mem-fraction-static (default 0.90)
#   LLM_EXTRA_ARGS   extra flags appended verbatim to the engine command
#
# On 8x H100, FP8 must use TEP8 (TP8 + expert parallel) via --ep-size, not plain
# TP8, because of the 512-expert MoE layout. If GPU memory is tight, lower
# MAX_MODEL_LEN or GPU_MEM_UTIL.

set -euo pipefail

model="${LLM_MODEL:-Qwen/Qwen3.8-Flash-Next-FP8}"
host="${LLM_HOST:-0.0.0.0}"
port="${LLM_PORT:-8003}"
tp_size="${TP_SIZE:-8}"
ep_size="${EP_SIZE:-8}"
max_model_len="${MAX_MODEL_LEN:-262144}"
gpu_mem_util="${GPU_MEM_UTIL:-0.90}"

read -r -a extra_args <<<"${LLM_EXTRA_ARGS:-}"

# The inference stack lives in a dedicated venv; the s6-generated init PATH does
# not include it, so reference the venv binary explicitly.
venv_bin="${LLM_VENV:-/opt/llm/venv}/bin"

exec "${venv_bin}/python" -m sglang.launch_server \
  --model-path "${model}" \
  --host "${host}" \
  --port "${port}" \
  --tp-size "${tp_size}" \
  --ep-size "${ep_size}" \
  --context-length "${max_model_len}" \
  --mem-fraction-static "${gpu_mem_util}" \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  "${extra_args[@]}"
