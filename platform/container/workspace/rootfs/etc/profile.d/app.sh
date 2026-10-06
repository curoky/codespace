#!/usr/bin/env bash

# shellcheck shell=bash

# rust
export CARGO_HOME=/opt/rust/cargo
export RUSTUP_HOME=/opt/rust/rustup
export PATH="$PATH:/opt/rust/cargo/bin"

# python
export UV_TOOL_DIR=/opt/uv/tools
export UV_TOOL_BIN_DIR=/opt/uv/bin
export UV_PYTHON_INSTALL_DIR=/opt/uv/python
export UV_PYTHON_BIN_DIR=/opt/uv/bin
export PATH="$PATH:/opt/uv/bin"
export PATH="$PATH:/opt/resource/opt/uv/bin"

# conda
export CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
export PATH="$PATH:/opt/conda/condabin"

# resource
export PATH="$PATH:/opt/resource/usr/local/bin"

# go
export PATH="$PATH:/opt/go/go1.27.1/bin"
# export GOPROXY="https://goproxy.cn,direct"

# llvm
export PATH="$PATH:/opt/llvm/llvm23.1.2/bin"

# java
export JAVA_HOME=/opt/java/openjdk27
export PATH="$PATH:/opt/java/tools/bin"
export PATH="$PATH:/opt/resource/opt/java/tools/bin"
export PATH="$PATH:$JAVA_HOME/bin"

# nodejs
export PATH="$PATH:/opt/node/tools/bin"
export PATH="$PATH:/opt/resource/opt/node/tools/bin"
export PATH="$PATH:/opt/node/nodejs24/bin"

# codespace
export PATH="$PATH:/opt/codespace-tools/java-tool"
export PATH="$PATH:/opt/codespace-tools/node-tool"
export PATH="$PATH:/opt/podman/bin"

# user
export PATH="/home/x/.local/bin:$PATH"

# nix
export PATH="$PATH:/nix/var/nix/profiles/default/bin"
export PATH="$PATH:/home/x/.local/state/nix/profiles/profile/bin"
export NIX_PATH="/home/x/.nix-defexpr/channels"

# cuda
export CUDA_HOME=/usr/local/cuda
export PATH="$PATH:/usr/local/cuda/bin:/opt/nvidia/nsight-systems-cli/2026.3.1/bin"
export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:/usr/local/cuda/lib64"

# kerberos
export KRB5CCNAME=/opt/secret/krb5_ccache

# trae
export TRAECLI_TRACE_ENABLED=false
export TRAECLI_TRACE_INGEST_ENDPOINT="http://127.0.0.1:1"
export TRAECLI_METRICS_ENDPOINT="http://127.0.0.1:1"
export TRAECLI_FILE_LOG_ENDPOINT="http://127.0.0.1:1"
export TRAE_ACTIVE_FEEDBACK_REPORT_ENDPOINT="http://127.0.0.1:1"
export TRAEX_FEEDBACK_UPLOAD_BASE_URL="http://127.0.0.1:1"
export TRAECLI_FEEDBACK_UPLOAD_BASE_URL="http://127.0.0.1:1"
export SEED_SUPER_RELAY_ENABLED=1
