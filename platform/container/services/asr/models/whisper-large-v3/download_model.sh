#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec uv run \
  --project "$model_dir" \
  --locked \
  --no-dev \
  hf download \
  openai/whisper-large-v3 \
  --revision 06f233fe06e710322aca913c1bc4249a0d71fce1 \
  --local-dir "$model_dir/weights" \
  --exclude '*.md' \
  --exclude '*.gif' \
  --exclude '*.png' \
  --exclude '*.mp4' \
  --exclude '*.h5' \
  --exclude 'example/*' \
  --exclude 'examples/*'
