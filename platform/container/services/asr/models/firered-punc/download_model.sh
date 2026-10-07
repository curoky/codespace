#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

exec uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  FireRedTeam/FireRedPunc \
  --revision e448fd967f44182a1c323cc30f5d89f2400c28da \
  --local-dir "$model_dir/weights" \
  --include 'chinese-bert-wwm-ext_vocab.txt' \
  --include 'chinese-lert-base/added_tokens.json' \
  --include 'chinese-lert-base/config.json' \
  --include 'chinese-lert-base/pytorch_model.bin' \
  --include 'chinese-lert-base/special_tokens_map.json' \
  --include 'chinese-lert-base/tokenizer.json' \
  --include 'chinese-lert-base/tokenizer_config.json' \
  --include 'chinese-lert-base/vocab.txt' \
  --include 'config.yaml' \
  --include 'model.pth.tar' \
  --include 'out_dict'
