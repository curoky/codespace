#!/usr/bin/env bash

set -euo pipefail

model="${SERVE_MODEL:-Qwen/Qwen3.8-Flash-Next-FP8}"
read -r -a extra_args <<<"${SERVE_EXTRA_ARGS:-}"

# This profile is coupled to one 8x H100 node. TP8 plus Triton expert parallel
# maps the FP8 MoE experts across NVLink; the upstream recipe also requires
# FlashInfer autotuning to remain disabled.
exec /opt/vllm/venv/bin/vllm serve "${model}" \
  --host 0.0.0.0 \
  --port 8080 \
  --tensor-parallel-size 8 \
  --enable-expert-parallel \
  --moe-backend triton \
  --max-model-len 262144 \
  --gpu-memory-utilization 0.85 \
  --no-enable-flashinfer-autotune \
  --enable-prefix-caching \
  --enable-chunked-prefill \
  --max-num-batched-tokens 8192 \
  --max-num-seqs 256 \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  "${extra_args[@]}"
