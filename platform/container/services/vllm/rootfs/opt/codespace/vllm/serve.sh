#!/usr/bin/env bash

# Launch the Qwen3.8-Flash-Next-FP8 OpenAI-compatible server with fixed tuning
# for one 8x H100 Host.
#
# Runtime inputs: SERVE_MODEL, SERVE_HOST, SERVE_PORT, and SERVE_EXTRA_ARGS.
#
# 显存紧张时经 SERVE_EXTRA_ARGS 降 --max-model-len / --gpu-memory-utilization，或设
# VLLM_PLE_CPU_OFFLOAD=1 把 51B N-gram 表卸到主机内存（需大内存 host）。

set -euo pipefail

model="${SERVE_MODEL:-Qwen/Qwen3.8-Flash-Next-FP8}"
host="${SERVE_HOST:-0.0.0.0}"
port="${SERVE_PORT:-8003}"

read -r -a extra_args <<<"${SERVE_EXTRA_ARGS:-}"

# The inference stack lives in a dedicated venv; the s6-generated init PATH does
# not include it, so reference the venv binary explicitly.
venv_bin="${SERVE_VENV:-/opt/codespace/vllm/venv}/bin"

exec "${venv_bin}/vllm" serve "${model}" \
  --host "${host}" \
  --port "${port}" \
  `# 8x H100 的 FP8 用 TP8 张量并行匹配 8 卡；全 NVLink mesh 下 all-reduce 廉价` \
  --tensor-parallel-size 8 \
  `# FP8 必须叠加 expert parallel（512 专家 MoE 布局要求），不能只用普通 TP8` \
  --enable-expert-parallel \
  `# Hopper 上 Qwen3.8-Flash-Next FP8 用 Triton MoE backend（官方 recipe 的 8x H100 配方要求）` \
  --moe-backend triton \
  `# 使用模型原生 262144 上下文` \
  --max-model-len 262144 \
  `# 静态显存占比 0.85（对齐官方 8x H100 recipe，给 Mamba/GDN state 与 activation 留余量），OOM 时经 SERVE_EXTRA_ARGS 再调小` \
  --gpu-memory-utilization 0.85 \
  `# 关闭 flashinfer autotune：Qwen3.8-Flash-Next 官方 recipe 要求，避免启动期长时间自动调优` \
  --no-enable-flashinfer-autotune \
  `# 开启前缀缓存复用相同 prompt 前缀，提升多轮/共享前缀场景吞吐` \
  --enable-prefix-caching \
  `# 分块 prefill：限制长 prompt 单步 prefill token 数，避免在较紧的 80GB 卡上撑爆 activation 显存并改善 prefill/decode 交织延迟` \
  --enable-chunked-prefill \
  --max-num-batched-tokens 8192 \
  `# 并发上限：640GB 显存 + FP8 权重留出较大 KV 空间，提高最大并发序列数以充分利用吞吐` \
  --max-num-seqs 256 \
  `# Qwen3 系列的工具调用（含自动选择）与推理内容解析器` \
  --enable-auto-tool-choice \
  --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 \
  "${extra_args[@]}"
