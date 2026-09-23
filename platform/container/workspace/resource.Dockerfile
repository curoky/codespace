# syntax=docker/dockerfile:1.9.0

# Payload-only image for the codespace-resource volume. Its contents are copied
# into a named Podman volume by `codespace resources sync --apply` and mounted
# read-only at /opt/resource in every Workspace. Nothing here is needed at boot.

# ----------------------------------- Rust -----------------------------------
FROM docker.io/debian:stable-slim AS stage_rust
ENV CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup
ENV PATH=/opt/rust/cargo/bin:${PATH}
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl https://sh.rustup.rs -sSf | sh -s -- -y --profile default --no-modify-path --default-toolchain stable \
  && rustup component remove rust-docs \
  && rm -rf /var/lib/apt/lists/*

# ------------------------- radare2 / rizin (binman) -------------------------
FROM docker.io/debian:latest AS stage_sb
RUN apt-get update -y && apt-get install -y curl zstd

COPY platform/container/workspace/config/binman-resource.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /usr/local/bin \
  && /usr/local/bin/bm sync /tmp/binman.yaml \
  && find /usr/local/store -type d -exec chmod 0755 {} +

# ----------------------------------- CUDA -----------------------------------
# CUDA 12.2 is the newest toolkit supported by the target Host's 535 driver.
FROM docker.io/nvidia/cuda:12.2.2-devel-ubuntu22.04 AS stage_cuda

# ----------------------------- Nsight Systems -------------------------------
FROM nvcr.io/nvidia/devtools/nsight-systems-cli:2026.3.1-ubuntu22.04 AS stage_nsys

# --------------------------------- Payload ----------------------------------
FROM docker.io/debian:stable-slim AS resource
COPY --from=stage_rust /opt/rust /opt/resource/opt/rust
COPY --from=stage_cuda /usr/local/cuda-12.2 /opt/resource/usr/local/cuda-12.2
COPY --from=stage_cuda /opt/nvidia/nsight-compute /opt/resource/opt/nvidia/nsight-compute
COPY --from=stage_nsys /opt/nvidia/nsight-systems-cli /opt/resource/opt/nvidia/nsight-systems-cli
COPY --from=stage_sb /usr/local/store/radare2 /opt/resource/usr/local/store/radare2
COPY --from=stage_sb /usr/local/store/rizin /opt/resource/usr/local/store/rizin
