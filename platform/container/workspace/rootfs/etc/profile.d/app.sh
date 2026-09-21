# shellcheck shell=sh

export CARGO_HOME=/opt/rust/cargo
export RUSTUP_HOME=/opt/rust/rustup
export PATH="$PATH:/opt/rust/cargo/bin"

export UV_TOOL_DIR=/opt/uv/tools
export UV_TOOL_BIN_DIR=/opt/uv/bin
export UV_PYTHON_INSTALL_DIR=/opt/uv/python
export UV_PYTHON_BIN_DIR=/opt/uv/bin
export PATH="$PATH:/opt/uv/bin"

export CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
export PATH="$PATH:/opt/conda/condabin"

export PATH="$PATH:/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec"

export PATH="$PATH:/nix/var/nix/profiles/default/bin"

export PATH="$PATH:/opt/podman/bin"

export CUDA_HOME=/usr/local/cuda
export PATH="$PATH:/usr/local/cuda/bin:/opt/nvidia/nsight-systems-cli/2026.3.1/bin"
export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:/usr/local/cuda/lib64"

export KRB5CCNAME=/opt/secret/krb5_ccache

export GOPROXY="https://goproxy.cn,direct"

export TRAECLI_TRACE_ENABLED=false
export TRAECLI_TRACE_INGEST_ENDPOINT="http://127.0.0.1:1"
export TRAECLI_METRICS_ENDPOINT="http://127.0.0.1:1"
export TRAECLI_FILE_LOG_ENDPOINT="http://127.0.0.1:1"
export TRAE_ACTIVE_FEEDBACK_REPORT_ENDPOINT="http://127.0.0.1:1"
export TRAEX_FEEDBACK_UPLOAD_BASE_URL="http://127.0.0.1:1"
export TRAECLI_FEEDBACK_UPLOAD_BASE_URL="http://127.0.0.1:1"
export SEED_SUPER_RELAY_ENABLED=1
