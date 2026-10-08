#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
revision=06f233fe06e710322aca913c1bc4249a0d71fce1

mkdir -p "$(readlink -m -- "$model_dir/weights")"

if [[ -f $model_dir/weights/.revision ]] && [[ $(<"$model_dir/weights/.revision") == "$revision" ]]; then
  exit 0
fi

uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  openai/whisper-large-v3 \
  --revision "$revision" \
  --local-dir "$model_dir/weights" \
  --include 'added_tokens.json' \
  --include 'config.json' \
  --include 'generation_config.json' \
  --include 'merges.txt' \
  --include 'model.safetensors' \
  --include 'normalizer.json' \
  --include 'preprocessor_config.json' \
  --include 'special_tokens_map.json' \
  --include 'tokenizer.json' \
  --include 'tokenizer_config.json' \
  --include 'vocab.json'

printf '%s\n' "$revision" >"$model_dir/weights/.revision"
