#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  OpenMOSS-Team/MOSS-Audio-8B-Instruct \
  --revision d4dc5a6d8cd79b43dcd82884c75e303b1ecd016d \
  --local-dir "$model_dir/weights" \
  --include 'added_tokens.json' \
  --include 'chat_template.jinja' \
  --include 'config.json' \
  --include 'configuration_moss_audio.py' \
  --include 'generation_config.json' \
  --include 'merges.txt' \
  --include 'model-*.safetensors' \
  --include 'model.safetensors.index.json' \
  --include 'preprocessor_config.json' \
  --include 'processing_moss_audio.py' \
  --include 'processor_config.json' \
  --include 'special_tokens_map.json' \
  --include 'tokenizer_config.json' \
  --include 'vocab.json'
