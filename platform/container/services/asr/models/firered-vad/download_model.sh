#!/usr/bin/env bash

set -euo pipefail

model_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# SDK 从 weights/VAD 加载，不是权重仓库根目录。
exec uv run \
  --project "$model_dir" \
  --locked \
  --no-dev \
  hf download \
  FireRedTeam/FireRedVAD \
  --revision 7990aaccc6b7aec1e527743bd30201f2c4a03b8c \
  --local-dir "$model_dir/weights" \
  --include 'VAD/*'
