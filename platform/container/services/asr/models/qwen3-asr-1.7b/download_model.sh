#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
revision=7278e1e70fe206f11671096ffdd38061171dd6e5

mkdir -p "$(readlink -m -- "$model_dir/weights")"

if [[ -f $model_dir/weights/.revision ]] && [[ $(<"$model_dir/weights/.revision") == "$revision" ]]; then
  exit 0
fi

# 普通权重供 vLLM 使用；-hf 变体面向原生 Transformers，不能混用。
uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  Qwen/Qwen3-ASR-1.7B \
  --revision "$revision" \
  --local-dir "$model_dir/weights" \
  --include 'chat_template.json' \
  --include 'config.json' \
  --include 'generation_config.json' \
  --include 'merges.txt' \
  --include 'model-*.safetensors' \
  --include 'model.safetensors.index.json' \
  --include 'preprocessor_config.json' \
  --include 'tokenizer_config.json' \
  --include 'vocab.json'

printf '%s\n' "$revision" >"$model_dir/weights/.revision"
