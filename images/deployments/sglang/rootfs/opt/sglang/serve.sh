#!/usr/bin/env bash

# SGLang entrypoint for the host-level Qwen3.8-Flash-Next-FP8 serving image. Reads
# knobs from the container environment and launches an OpenAI-compatible server.
# Model weights are never baked in: the ~172 GiB FP8 weights are resolved from a
# bind-mounted Hugging Face cache (HF_HOME) and pulled on first start.
#
# 针对实测 host GPU 拓扑（nvidia-smi）调优：8x NVIDIA H100 80GB HBM3、compute
# capability 9.0（Hopper，原生 FP8 e4m3）、全互联 NVLink（NV18 / NVSwitch，
# ~900 GB/s）、双 NUMA（GPU0-3→node0，GPU4-7→node1）。优化参数已按此拓扑写死，
# 只有部署环境相关的 model/host/port 保留为环境变量。
#
# Environment knobs:
#   SERVE_MODEL        model id or local path (default Qwen/Qwen3.8-Flash-Next-FP8)
#   SERVE_HOST         bind address inside the container (default 0.0.0.0)
#   SERVE_PORT         OpenAI API port inside the container (default 8003)
#   SERVE_EXTRA_ARGS   extra flags appended verbatim to the engine command

set -euo pipefail

model="${SERVE_MODEL:-Qwen/Qwen3.8-Flash-Next-FP8}"
host="${SERVE_HOST:-0.0.0.0}"
port="${SERVE_PORT:-8003}"

read -r -a extra_args <<<"${SERVE_EXTRA_ARGS:-}"

# The inference stack lives in a dedicated venv; the s6-generated init PATH does
# not include it, so reference the venv binary explicitly.
venv_bin="${SERVE_VENV:-/opt/sglang/venv}/bin"

# sgl-deep-gemm JIT-compiles FP8 kernels at import time and requires a real CUDA
# Toolkit (nvcc + headers). The image installs it under /usr/local/cuda-12.9 (see
# Dockerfile); export CUDA_HOME/PATH here as a belt-and-suspenders fallback in
# case the s6 environment snapshot does not carry the Dockerfile ENV through to
# this process. Without CUDA_HOME, `import deep_gemm` aborts with
# `AssertionError` from find_cuda_home().
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda-12.9}"
export PATH="${CUDA_HOME}/bin:${PATH}"

exec "${venv_bin}/python" -m sglang.launch_server \
  --model-path "${model}" \
  --host "${host}" \
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
  `# GDN + QSA 混合架构必需：线性注意力层走 flashinfer 后端、SSM state 用 bfloat16（cookbook recipe）` \
  --linear-attn-prefill-backend flashinfer \
  --linear-attn-decode-backend flashinfer \
  --mamba-ssm-dtype bfloat16 \
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
  "${extra_args[@]}"
