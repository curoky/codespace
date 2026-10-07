#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec uv run \
  --project "$model_dir" \
  --locked \
  --no-dev \
  hf download \
  FunAudioLLM/SenseVoiceSmall \
  --revision 3847d57b6bdf2dd8875cb1508d2af43d80a16bf7 \
  --local-dir "$model_dir/weights" \
  --include 'am.mvn' \
  --include 'chn_jpn_yue_eng_ko_spectok.bpe.model' \
  --include 'config.yaml' \
  --include 'configuration.json' \
  --include 'model.pt'
