#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# 固定 Hugging Face 普通版；FunASR 的同名 ModelScope 简称指向 SeACo 热词版。
exec uv run \
  --project "$model_dir" \
  --locked \
  --no-dev \
  hf download \
  funasr/paraformer-zh \
  --revision d7811ee3ac581fbcfdeb37c98c6ba674028433dc \
  --local-dir "$model_dir/weights" \
  --include 'am.mvn' \
  --include 'config.yaml' \
  --include 'configuration.json' \
  --include 'model.pt' \
  --include 'seg_dict' \
  --include 'tokens.json'
