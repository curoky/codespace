#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
revision=f667ed73aee57d40cc39428eb768b4fd87a0a29e

mkdir -p "$(readlink -m -- "$model_dir/weights")"

if [[ -f $model_dir/weights/.revision ]] && [[ $(<"$model_dir/weights/.revision") == "$revision" ]]; then
  exit 0
fi

# NeMo 恢复 .nemo checkpoint；无需同时下载 safetensors 或 GGUF。
uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  nvidia/Nemotron-3-Diarization \
  --revision "$revision" \
  --local-dir "$model_dir/weights" \
  --include '*.nemo'

printf '%s\n' "$revision" >"$model_dir/weights/.revision"
