#!/usr/bin/env bash

set -euo pipefail

model="${SERVE_MODEL:-Qwen/Qwen3.8-Flash-Next-FP8}"

export SGLANG_ENABLE_TP_MEMORY_INBALANCE_CHECK=false
export CUDA_HOME=/usr/local/cuda-12.9
export PATH="${CUDA_HOME}/bin:${PATH}"

# This profile is coupled to one 8x H100 node. TP8 plus EP8 maps the FP8 MoE
# experts across NVLink. GDN uses FlashInfer with float32 state, and NEXTN uses
# the checkpoint's MTP head rather than a separate draft model.
exec /opt/sglang/venv/bin/python -m sglang.launch_server \
  --model-path "${model}" \
  --host 0.0.0.0 \
  --port 8080 \
  --tp-size 8 \
  --ep-size 8 \
  --context-length 262144 \
  --mem-fraction-static 0.85 \
  --chunked-prefill-size 8192 \
  --linear-attn-prefill-backend flashinfer \
  --linear-attn-decode-backend flashinfer \
  --mamba-ssm-dtype float32 \
  --max-running-requests 96 \
  --speculative-algorithm NEXTN \
  --speculative-num-steps 3 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4 \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --cuda-graph-backend-decode disabled
