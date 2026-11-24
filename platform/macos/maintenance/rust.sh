#!/usr/bin/env bash
set -euo pipefail

export CARGO_HOME="$HOME/.local/opt/rust/cargo"
export RUSTUP_HOME="$HOME/.local/opt/rust/rustup"
export PATH="$CARGO_HOME/bin:$PATH"

if [[ ! -x "$CARGO_HOME/bin/rustup" ]]; then
  work_dir="$(mktemp -d)"
  trap 'rm -rf "$work_dir"' EXIT
  curl -fsSL https://sh.rustup.rs -o "$work_dir/rustup-init.sh"
  bash "$work_dir/rustup-init.sh" -y --no-modify-path --default-toolchain none
fi

"$CARGO_HOME/bin/rustup" toolchain install stable --profile default
"$CARGO_HOME/bin/rustup" component add rust-src rust-analyzer llvm-tools --toolchain stable
"$CARGO_HOME/bin/rustup" component remove rust-docs --toolchain stable
"$CARGO_HOME/bin/rustup" default stable
