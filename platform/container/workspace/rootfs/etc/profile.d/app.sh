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
export PATH="$PATH:/nix/var/nix/profiles/default/bin"

# cuda
export CUDA_HOME=/usr/local/cuda
export PATH="$PATH:/usr/local/cuda/bin:/opt/nvidia/nsight-systems-cli/2026.3.1/bin"
export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:+$LD_LIBRARY_PATH:}/usr/local/cuda/lib64"
