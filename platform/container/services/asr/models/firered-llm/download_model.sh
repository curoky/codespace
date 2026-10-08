#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
revision=24078c33d69cafe365e343af5b1894548879707d

mkdir -p "$(readlink -m -- "$model_dir/weights")"

if [[ -f $model_dir/weights/.revision ]] && [[ $(<"$model_dir/weights/.revision") == "$revision" ]]; then
  exit 0
fi

# FireRed 作者引用的社区 vLLM 转换权重；原始 SDK checkpoint 不能直接替换。
uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  allendou/FireRedASR2-LLM-vllm \
  --revision "$revision" \
  --local-dir "$model_dir/weights" \
  --include 'cmvn.ark' \
  --include 'config.json' \
  --include 'dict.txt' \
  --include 'generation_config.json' \
  --include 'merges.txt' \
  --include 'model-*.safetensors' \
  --include 'preprocessor_config.json' \
  --include 'tokenizer.json' \
  --include 'tokenizer_config.json' \
  --include 'train_bpe1000.model' \
  --include 'vocab.json'

printf '%s\n' "$revision" >"$model_dir/weights/.revision"
