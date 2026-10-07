#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec uv run \
  --project "$model_dir" \
  --locked \
  --no-dev \
  hf download \
  OpenMOSS-Team/MOSS-Audio-8B-Instruct \
  --revision d4dc5a6d8cd79b43dcd82884c75e303b1ecd016d \
  --local-dir "$model_dir/weights" \
  --exclude '*.md' \
  --exclude '*.gif' \
  --exclude '*.png' \
  --exclude '*.mp4' \
  --exclude '*.h5' \
  --exclude 'example/*' \
  --exclude 'examples/*'
