# shellcheck shell=sh

# rust
export CARGO_HOME=/opt/rust/cargo
export RUSTUP_HOME=/opt/rust/rustup
export PATH="$PATH:/opt/rust/cargo/bin"

# uv
export UV_TOOL_DIR=/opt/uv/tools
export UV_TOOL_BIN_DIR=/opt/uv/bin
export UV_PYTHON_INSTALL_DIR=/opt/uv/python
export UV_PYTHON_BIN_DIR=/opt/uv/bin
export PATH="$PATH:/opt/uv/bin"

# conda
export CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
export PATH="$PATH:/opt/conda/condabin"

# bm
export PATH="$PATH:/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec"

# nix
export PATH="$PATH:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin"

# cuda
export CUDA_HOME=/usr/local/cuda
export PATH="$PATH:/usr/local/cuda/bin:/opt/nvidia/nsight-systems-cli/2026.3.1/bin"
export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:/usr/local/cuda/lib64"

# trae
# 遥测三链路
export TRAECLI_TRACE_ENABLED=false                        # trace 硬开关（反编译确认，env 优先级最高）
export TRAECLI_TRACE_INGEST_ENDPOINT="http://127.0.0.1:1" # trace 端点导向黑洞
export TRAECLI_METRICS_ENDPOINT="http://127.0.0.1:1"      # metrics 端点
export TRAECLI_FILE_LOG_ENDPOINT="http://127.0.0.1:1"     # 本地文件日志上报端点
# 反馈上报
export TRAE_ACTIVE_FEEDBACK_REPORT_ENDPOINT="http://127.0.0.1:1"
export TRAEX_FEEDBACK_UPLOAD_BASE_URL="http://127.0.0.1:1"
export TRAECLI_FEEDBACK_UPLOAD_BASE_URL="http://127.0.0.1:1"
export SEED_SUPER_RELAY_ENABLED=1