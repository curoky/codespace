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
  --include 'chat_template.json' \
  --include 'config.json' \
  --include 'generation_config.json' \
  --include 'merges.txt' \
  --include 'model.safetensors' \
  --include 'preprocessor_config.json' \
  --include 'tokenizer_config.json' \
  --include 'vocab.json'
