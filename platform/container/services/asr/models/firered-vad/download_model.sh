#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
revision=7990aaccc6b7aec1e527743bd30201f2c4a03b8c

mkdir -p "$(readlink -m -- "$model_dir/weights")"

if [[ -f $model_dir/weights/.revision ]] && [[ $(<"$model_dir/weights/.revision") == "$revision" ]]; then
  exit 0
fi

# SDK 从 weights/VAD 加载，不是权重仓库根目录。
uv run \
  --project "$model_dir" \
  --frozen \
  --no-sync \
  hf download \
  FireRedTeam/FireRedVAD \
  --revision "$revision" \
  --local-dir "$model_dir/weights" \
  --include 'VAD/*'

printf '%s\n' "$revision" >"$model_dir/weights/.revision"
