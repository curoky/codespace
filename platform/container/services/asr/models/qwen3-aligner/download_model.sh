#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# vLLM token classification 使用普通权重，非原生 Transformers 的 -hf 变体。
exec uv run \
  --project "$model_dir" \
  --locked \
  --no-dev \
  hf download \
  Qwen/Qwen3-ForcedAligner-0.6B \
  --revision c7cbfc2048c462b0d63a45797104fc9db3ad62b7 \
  --local-dir "$model_dir/weights" \
  --exclude '*.md' \
  --exclude '*.gif' \
  --exclude '*.png' \
  --exclude '*.mp4' \
  --exclude '*.h5' \
  --exclude 'example/*' \
  --exclude 'examples/*'
