#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
revision=3533c8cf8e369892e6b79ff1bf80f7b0286a54ee

mkdir -p "$(readlink -m -- "$model_dir/weights")"

if [[ -f $model_dir/weights/.revision ]] && [[ $(<"$model_dir/weights/.revision") == "$revision" ]]; then
  exit 0
fi

# 先在模型页接受访问条件，凭据放在 x 用户的默认 HF token 文件中。
# 需要完整 pipeline、segmentation 与 embedding 资产，不能只下载单个权重。
uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  pyannote/speaker-diarization-community-1 \
  --revision "$revision" \
  --local-dir "$model_dir/weights" \
  --include 'config.yaml' \
  --include 'embedding/pytorch_model.bin' \
  --include 'plda/*.npz' \
  --include 'segmentation/pytorch_model.bin'

printf '%s\n' "$revision" >"$model_dir/weights/.revision"
