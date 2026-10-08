#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
revision=3847d57b6bdf2dd8875cb1508d2af43d80a16bf7

mkdir -p "$(readlink -m -- "$model_dir/weights")"

if [[ -f $model_dir/weights/.revision ]] && [[ $(<"$model_dir/weights/.revision") == "$revision" ]]; then
  exit 0
fi

uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  FunAudioLLM/SenseVoiceSmall \
  --revision "$revision" \
  --local-dir "$model_dir/weights" \
  --include \
  'am.mvn' \
  'chn_jpn_yue_eng_ko_spectok.bpe.model' \
  'config.yaml' \
  'configuration.json' \
  'model.pt'

printf '%s\n' "$revision" >"$model_dir/weights/.revision"
