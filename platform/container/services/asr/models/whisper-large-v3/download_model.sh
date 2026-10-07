#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  openai/whisper-large-v3 \
  --revision 06f233fe06e710322aca913c1bc4249a0d71fce1 \
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
