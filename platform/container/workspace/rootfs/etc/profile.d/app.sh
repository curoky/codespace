#!/usr/bin/env bash

# shellcheck shell=bash

# 首次加载让受管工具优先于系统工具；重复加载不重排调用方的 PATH。
codespace_paths=
codespace_add_path() {
  case ":${PATH:-}:${codespace_paths}:" in
    *":$1:"*) ;;
    *) codespace_paths="${codespace_paths:+$codespace_paths:}$1" ;;
  esac
}

# user tools
codespace_add_path "$HOME/.local/bin"

# rust
export CARGO_HOME="$HOME/.cargo"
export RUSTUP_HOME="$HOME/.local/opt/rust/rustup"
codespace_add_path "$CARGO_HOME/bin"
codespace_add_path "$HOME/.local/opt/rust/cargo/bin"

# python
export UV_TOOL_DIR="$HOME/.local/opt/uv/tools"
export UV_TOOL_BIN_DIR="$HOME/.local/opt/uv/bin"
export UV_PYTHON_INSTALL_DIR="$HOME/.local/opt/uv/python"
export UV_PYTHON_BIN_DIR="$HOME/.local/opt/uv/bin"
codespace_add_path "$UV_TOOL_BIN_DIR"
codespace_add_path "$UV_PYTHON_BIN_DIR"
codespace_add_path /opt/resource/home/x/.local/opt/uv/bin

# conda
export CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
codespace_add_path "$HOME/.local/opt/conda/condabin"

# resource
codespace_add_path /opt/resource/usr/local/bin

# go
codespace_add_path "$HOME/go/bin"
codespace_add_path "$HOME/.local/opt/go/go1.27/bin"
codespace_add_path /usr/local/profile/go/bin

# llvm
codespace_add_path "$HOME/.local/opt/llvm/llvm23/bin"
codespace_add_path /usr/local/profile/clang-tools/bin

# protobuf
codespace_add_path /usr/local/profile/protobuf/bin

# java
export JAVA_HOME="$HOME/.local/opt/java/openjdk27"
codespace_add_path "$HOME/.local/opt/java"
codespace_add_path "$HOME/.local/opt/java/tools/bin"
codespace_add_path /opt/resource/home/x/.local/opt/java/tools/bin
codespace_add_path "$JAVA_HOME/bin"

# nodejs
export NPM_CONFIG_CACHE="$HOME/.cache/npm"
codespace_add_path "$HOME/.local/share/pnpm/bin"
codespace_add_path "$HOME/.local/opt/node"
codespace_add_path "$HOME/.local/opt/node/tools/bin"
codespace_add_path "$HOME/.local/opt/node/nodejs26/bin"

# codespace
export WORKSPACE=/workspace
codespace_add_path /opt/podman/bin

# buildah
export BUILDAH_ISOLATION=chroot

# nix
export NIX_PATH="$HOME/.nix-defexpr/channels"
codespace_add_path /nix/var/nix/profiles/default/bin
codespace_add_path "$HOME/.local/state/nix/profiles/profile/bin"

# cuda
export CUDA_HOME=/usr/local/cuda
codespace_add_path "$CUDA_HOME/bin"
codespace_add_path /opt/nvidia/nsight-systems-cli/2026.3.1/bin
export LD_LIBRARY_PATH=/usr/local/cuda/lib64

# kerberos
export KRB5CCNAME=/opt/secret/krb5_ccache

# tmux
export TMUX_CONF_LOCAL="$HOME/.config/tmux/tmux.conf.local"

export PATH="${codespace_paths:+$codespace_paths:}${PATH:-}"
unset codespace_paths
unset -f codespace_add_path

# trae
export TRAECLI_TRACE_ENABLED=false
export TRAECLI_TRACE_INGEST_ENDPOINT="http://127.0.0.1:1"
export TRAECLI_METRICS_ENDPOINT="http://127.0.0.1:1"
export TRAECLI_FILE_LOG_ENDPOINT="http://127.0.0.1:1"
export TRAE_ACTIVE_FEEDBACK_REPORT_ENDPOINT="http://127.0.0.1:1"
export TRAEX_FEEDBACK_UPLOAD_BASE_URL="http://127.0.0.1:1"
export TRAECLI_FEEDBACK_UPLOAD_BASE_URL="http://127.0.0.1:1"
export SEED_SUPER_RELAY_ENABLED=1
