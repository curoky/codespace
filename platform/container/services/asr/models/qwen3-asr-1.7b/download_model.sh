#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# 普通权重供 vLLM 使用；-hf 变体面向原生 Transformers，不能混用。
exec uv run \
  --project "$model_dir" \
  --locked \
  --no-dev \
  hf download \
  Qwen/Qwen3-ASR-1.7B \
  --revision 7278e1e70fe206f11671096ffdd38061171dd6e5 \
  --local-dir "$model_dir/weights" \
  --exclude '*.md' \
  --exclude '*.gif' \
  --exclude '*.png' \
  --exclude '*.mp4' \
  --exclude '*.h5' \
  --exclude 'example/*' \
  --exclude 'examples/*'
