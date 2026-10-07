#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# FireRed 作者引用的社区 vLLM 转换权重；原始 SDK checkpoint 不能直接替换。
exec uv run \
  --project "$model_dir" \
  --locked \
  --no-dev \
  hf download \
  allendou/FireRedASR2-LLM-vllm \
  --revision 24078c33d69cafe365e343af5b1894548879707d \
  --local-dir "$model_dir/weights" \
  --exclude '*.md' \
  --exclude '*.gif' \
  --exclude '*.png' \
  --exclude '*.mp4' \
  --exclude '*.h5' \
  --exclude 'example/*' \
  --exclude 'examples/*'
