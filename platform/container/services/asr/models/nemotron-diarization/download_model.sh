#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# NeMo 恢复 .nemo checkpoint；无需同时下载 safetensors 或 GGUF。
exec uv run \
  --project "$model_dir" \
  --locked \
  --no-dev \
  hf download \
  nvidia/Nemotron-3-Diarization \
  --revision f667ed73aee57d40cc39428eb768b4fd87a0a29e \
  --local-dir "$model_dir/weights" \
  --include '*.nemo'
