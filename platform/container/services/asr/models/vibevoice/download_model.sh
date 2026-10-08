#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
revision=f22241c2062b3b25272bf117397e03d73381037a

mkdir -p "$(readlink -m -- "$model_dir/weights")"

if [[ -f $model_dir/weights/.revision ]] && [[ $(<"$model_dir/weights/.revision") == "$revision" ]]; then
  exit 0
fi

# 原生 vLLM 使用 HF architecture；原始 VibeVoice-ASR 配套旧 plugin。
uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  microsoft/VibeVoice-ASR-HF \
  --revision "$revision" \
  --local-dir "$model_dir/weights" \
  --include 'chat_template.jinja' \
  --include 'config.json' \
  --include 'generation_config.json' \
  --include 'model-*.safetensors' \
  --include 'model.safetensors.index.json' \
  --include 'processor_config.json' \
  --include 'tokenizer.json' \
  --include 'tokenizer_config.json'

printf '%s\n' "$revision" >"$model_dir/weights/.revision"
