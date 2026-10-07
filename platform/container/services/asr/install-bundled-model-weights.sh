#!/usr/bin/env bash

set -euo pipefail

if [[ -z ${HF_TOKEN_PATH:-} || ! -s $HF_TOKEN_PATH ]]; then
  echo "HF_TOKEN_PATH must point to a non-empty Hugging Face token" >&2
  exit 1
fi

# Check gated access before downloading the larger public checkpoints.
readonly bundled_models=(
  pyannote-community-1
  firered-punc
  firered-vad
  nemotron-diarization
  paraformer
  qwen3-aligner
  sensevoice
)

for model in "${bundled_models[@]}"; do
  model_dir="/opt/asr/models/$model"
  if [[ ! -x $model_dir/download_model.sh ]]; then
    echo "missing download_model.sh for bundled model $model" >&2
    exit 1
  fi

  echo "downloading bundled model $model"
  "$model_dir/download_model.sh"
  rm -rf -- "$model_dir/weights/.cache"
done
