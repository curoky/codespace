#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
revision=704aa4a9c304e8520be88901e0d1960158ef5b15

mkdir -p "$(readlink -m -- "$model_dir/weights")"

if [[ -f $model_dir/weights/.revision ]] && [[ $(<"$model_dir/weights/.revision") == "$revision" ]]; then
  exit 0
fi

uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  OpenMOSS-Team/MOSS-Transcribe-Diarize \
  --revision "$revision" \
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

printf '%s\n' "$revision" >"$model_dir/weights/.revision"
