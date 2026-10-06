#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
macos_dir="$(cd "$script_dir/.." && pwd -P)"

if [[ $# -ne 1 ]]; then
  printf 'usage: %s OUTPUT.tar.gz\n' "$0" >&2
  exit 2
fi
if [[ "$(uname -s)/$(uname -m)" != "Darwin/arm64" ]]; then
  printf 'error: the bm bundle must be built on Darwin/arm64\n' >&2
  exit 1
fi

output="$1"
if [[ "$output" != /* ]]; then
  output="$(pwd -P)/$output"
fi
mkdir -p "$(dirname "$output")"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

curl -fsSL \
  https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
  -o "$work_dir/install-binman.sh"
/bin/bash "$work_dir/install-binman.sh" --prefix "$work_dir/root/bm"

"$work_dir/root/bm/bin/bm" \
  --prefix "$work_dir/root/bm" \
  install \
  --file "$macos_dir/binman.yaml"
ln -sfn bazelisk "$work_dir/root/bm/bin/bazel"

tar -C "$work_dir/root" -czf "$output" bm
printf 'built %s\n' "$output"
