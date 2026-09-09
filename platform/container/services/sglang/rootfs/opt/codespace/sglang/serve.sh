#!/usr/bin/env bash

# Launch the Qwen3.8-Flash-Next-FP8 OpenAI-compatible server with fixed tuning
# for one 8x H100 Host.
#
# Runtime inputs: SERVE_MODEL and SERVE_PORT.

set -euo pipefail

model="${SERVE_MODEL:-Qwen/Qwen3.8-Flash-Next-FP8}"
port="${SERVE_PORT:-8003}"

# The inference stack lives in a dedicated venv; the s6-generated init PATH does
# not include it, so reference the venv binary explicitly.
venv_bin="${SERVE_VENV:-/opt/codespace/sglang/venv}/bin"

export SGLANG_ENABLE_TP_MEMORY_INBALANCE_CHECK=false

# sgl-deep-gemm JIT-compiles FP8 kernels at import time. Export the toolkit path
# explicitly because the s6 environment snapshot can replace image environment.
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda-12.9}"
export PATH="${CUDA_HOME}/bin:${PATH}"

exec "${venv_bin}/python" -m sglang.launch_server \
  --model-path "${model}" \
  --host 127.0.0.1 \
  --port "${port}" \
  `# 8x H100 的 FP8 必须用 TEP8（TP8 + Expert Parallel）承载 512 专家 MoE 布局；全 NVLink mesh 下 TP8 all-reduce 廉价，无需 --enable-p2p-check` \
  --tp-size 8 \
  --ep-size 8 \
  `# 使用模型原生 262144 上下文` \
  --context-length 262144 \
  `# 权重+KV pool 的静态显存占比；0.85 给独立的 Mamba/GDN state cache 与 activation 在 80GB 上留余量，OOM 时优先调小此值或上下文` \
  --mem-fraction-static 0.85 \
  `# 限制单步 prefill token 数，避免长 prompt 在较紧的 80GB 卡上撑爆 activation 显存` \
  --chunked-prefill-size 8192 \
  `# GDN + QSA 混合架构必需：线性注意力层走 flashinfer 后端，FlashInfer initial state 使用 float32` \
  --linear-attn-prefill-backend flashinfer \
  --linear-attn-decode-backend flashinfer \
  --mamba-ssm-dtype float32 \
  `# 并发上限；去掉该 flag 会回落到默认 48，此处提到 96 以充分利用 640GB 显存` \
  --max-running-requests 96 \
  `# NEXTN speculative decoding：复用 checkpoint 内置的 MTP head 提升吞吐（cookbook recipe）` \
  --speculative-algorithm NEXTN \
  --speculative-num-steps 3 \
  --speculative-eagle-topk 1 \
  --speculative-num-draft-tokens 4 \
  `# Qwen3 系列的工具调用与推理内容解析器` \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  --cuda-graph-backend-decode disabled
