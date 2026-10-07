#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  OpenMOSS-Team/MOSS-Transcribe-Diarize \
  --revision 704aa4a9c304e8520be88901e0d1960158ef5b15 \
  --local-dir "$model_dir/weights" \
  --include 'added_tokens.json' \
  --include 'chat_template.jinja' \
  --include 'config.json' \
  --include 'configuration_moss_transcribe_diarize.py' \
  --include 'generation_config.json' \
  --include 'merges.txt' \
  --include 'model-*.safetensors' \
  --include 'model.safetensors.index.json' \
  --include 'modeling_moss_transcribe_diarize.py' \
  --include 'preprocessor_config.json' \
  --include 'processing_moss_transcribe_diarize.py' \
  --include 'processor_config.json' \
  --include 'special_tokens_map.json' \
  --include 'tokenizer.json' \
  --include 'tokenizer_config.json' \
  --include 'vocab.json'
