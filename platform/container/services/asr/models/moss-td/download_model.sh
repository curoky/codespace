#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec uv run \
  --project "$model_dir" \
  --locked \
  --no-dev \
  hf download \
  OpenMOSS-Team/MOSS-Transcribe-Diarize \
  --revision 704aa4a9c304e8520be88901e0d1960158ef5b15 \
  --local-dir "$model_dir/weights" \
  --exclude '*.md' \
  --exclude '*.gif' \
  --exclude '*.png' \
  --exclude '*.mp4' \
  --exclude '*.h5' \
  --exclude 'example/*' \
  --exclude 'examples/*'
