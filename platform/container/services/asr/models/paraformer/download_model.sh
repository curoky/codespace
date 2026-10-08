#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
revision=d7811ee3ac581fbcfdeb37c98c6ba674028433dc

mkdir -p "$(readlink -m -- "$model_dir/weights")"

if [[ -f $model_dir/weights/.revision ]] && [[ $(<"$model_dir/weights/.revision") == "$revision" ]]; then
  exit 0
fi

# 固定 Hugging Face 普通版；FunASR 的同名 ModelScope 简称指向 SeACo 热词版。
uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  funasr/paraformer-zh \
  --revision "$revision" \
  --local-dir "$model_dir/weights" \
  --include \
  'am.mvn' \
  'config.yaml' \
  'configuration.json' \
  'model.pt' \
  'seg_dict' \
  'tokens.json'

printf '%s\n' "$revision" >"$model_dir/weights/.revision"
