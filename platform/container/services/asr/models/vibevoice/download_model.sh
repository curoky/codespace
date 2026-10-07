#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# 原生 vLLM 使用 HF architecture；原始 VibeVoice-ASR 配套旧 plugin。
exec uv run \
  --project "$model_dir" \
  --locked \
  --no-dev \
  hf download \
  microsoft/VibeVoice-ASR-HF \
  --revision f22241c2062b3b25272bf117397e03d73381037a \
  --local-dir "$model_dir/weights" \
  --exclude '*.md' \
  --exclude '*.gif' \
  --exclude '*.png' \
  --exclude '*.mp4' \
  --exclude '*.h5' \
  --exclude 'example/*' \
  --exclude 'examples/*'
