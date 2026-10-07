#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# 原生 vLLM 使用 HF architecture；原始 VibeVoice-ASR 配套旧 plugin。
exec uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  microsoft/VibeVoice-ASR-HF \
  --revision f22241c2062b3b25272bf117397e03d73381037a \
  --local-dir "$model_dir/weights" \
  --include 'chat_template.jinja' \
  --include 'config.json' \
  --include 'generation_config.json' \
  --include 'model-*.safetensors' \
  --include 'model.safetensors.index.json' \
  --include 'processor_config.json' \
  --include 'tokenizer.json' \
  --include 'tokenizer_config.json'
