#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
revision=c7cbfc2048c462b0d63a45797104fc9db3ad62b7

mkdir -p "$(readlink -m -- "$model_dir/weights")"

if [[ -f $model_dir/weights/.revision ]] && [[ $(<"$model_dir/weights/.revision") == "$revision" ]]; then
  exit 0
fi

# vLLM token classification 使用普通权重，非原生 Transformers 的 -hf 变体。
uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  Qwen/Qwen3-ForcedAligner-0.6B \
  --revision "$revision" \
  --local-dir "$model_dir/weights" \
  --include 'chat_template.json' \
  --include 'config.json' \
  --include 'generation_config.json' \
  --include 'merges.txt' \
  --include 'model.safetensors' \
  --include 'preprocessor_config.json' \
  --include 'tokenizer_config.json' \
  --include 'vocab.json'

printf '%s\n' "$revision" >"$model_dir/weights/.revision"
