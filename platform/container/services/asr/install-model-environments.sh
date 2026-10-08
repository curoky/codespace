#!/usr/bin/env bash

set -euo pipefail

shopt -s nullglob
model_dirs=(/opt/asr/models/*/)

if ((${#model_dirs[@]} == 0)); then
  echo "no ASR model directories found" >&2
  exit 1
fi

export UV_LINK_MODE=hardlink

for model_dir in "${model_dirs[@]}"; do
  if [[ ! -f "$model_dir/pyproject.toml" ]]; then
    echo "missing pyproject.toml in $model_dir" >&2
    exit 1
  fi

  echo "installing ${model_dir%/}"
  if ! uv sync \
    --locked \
    --no-dev \
    --no-install-package cuda-toolkit \
    --no-install-package nvidia-cuda-crt \
    --no-install-package nvidia-cuda-nvcc \
    --no-install-package nvidia-nvvm \
    --project "$model_dir"; then
    echo "failed to install ${model_dir%/}" >&2
    exit 1
  fi
done
