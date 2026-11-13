#!/usr/bin/env bash

# shellcheck shell=bash

# 多个 shell 入口会加载此文件；只补齐缺失目录，保留调用方的优先级。
codespace_add_path() {
  case ":${PATH:-}:" in
    *":$1:"*) ;;
    *) PATH="${PATH:+$PATH:}$1" ;;
  esac
  export PATH
}

# user
codespace_add_path /home/x/.local/bin

# rust
export CARGO_HOME=/home/x/.cargo
export RUSTUP_HOME=/opt/rust/rustup
codespace_add_path "$CARGO_HOME/bin"
codespace_add_path /opt/rust/cargo/bin

# python
export UV_TOOL_DIR=/opt/uv/tools
export UV_TOOL_BIN_DIR=/opt/uv/bin
export UV_PYTHON_INSTALL_DIR=/opt/uv/python
export UV_PYTHON_BIN_DIR=/opt/uv/bin
codespace_add_path "$UV_TOOL_BIN_DIR"
codespace_add_path "$UV_PYTHON_BIN_DIR"
codespace_add_path /opt/resource/opt/uv/bin

# conda
export CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
codespace_add_path /opt/conda/condabin

# resource
codespace_add_path /opt/resource/usr/local/bin

# go
codespace_add_path /opt/go/go1.27.1/bin
# export GOPROXY="https://goproxy.cn,direct"

# llvm
codespace_add_path /opt/llvm/llvm23.1.2/bin

# java
export JAVA_HOME=/opt/java/openjdk27
codespace_add_path /opt/java/java-tool
codespace_add_path /opt/java/tools/bin
codespace_add_path /opt/resource/opt/java/tools/bin
codespace_add_path "$JAVA_HOME/bin"

# nodejs
codespace_add_path /opt/node/node-tool
codespace_add_path /opt/node/tools/bin
codespace_add_path /opt/resource/opt/node/tools/bin
codespace_add_path /opt/node/nodejs24/bin

# codespace
codespace_add_path /opt/podman/bin

# buildah
export BUILDAH_ISOLATION=chroot

# nix
codespace_add_path /nix/var/nix/profiles/default/bin
codespace_add_path /home/x/.local/state/nix/profiles/profile/bin
export NIX_PATH="/home/x/.nix-defexpr/channels"

# cuda
export CUDA_HOME=/usr/local/cuda
codespace_add_path "$CUDA_HOME/bin"
codespace_add_path /opt/nvidia/nsight-systems-cli/2026.3.1/bin
export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:/usr/local/cuda/lib64"

# kerberos
export KRB5CCNAME=/opt/secret/krb5_ccache

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
