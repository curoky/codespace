# syntax=docker/dockerfile:1.9.0

# ----------------------------------- Rust -----------------------------------
FROM docker.io/debian:stable-slim AS stage_rust
ENV CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup
ENV PATH=/opt/rust/cargo/bin:${PATH}
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl https://sh.rustup.rs -sSf | sh -s -- -y --profile default --no-modify-path --default-toolchain stable \
  && rustup component remove rust-docs \
  && rm -rf /var/lib/apt/lists/*

# ---------------------------- Binman packages -------------------------------
FROM docker.io/debian:latest AS stage_sb
RUN apt-get update -y && apt-get install -y curl zstd

RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /usr/local \
  && /usr/local/bin/bm install --prefix /usr/local radare2 rizin \
  && /usr/local/bin/bm install --prefix /usr/local --link-to profile/go \
    gopls delve go-tools gofumpt golangci-lint gotests gotools impl revive \
  && find /usr/local/store -type d -exec chmod 0755 {} +

# ------------------------------------ Go ------------------------------------
FROM docker.io/debian:stable-slim AS stage_go
ADD --checksum=sha256:63d339f0da5ab53635a56f2490a7984dfe12dfcff22ad749f63edaf590168445 \
  https://go.dev/dl/go1.27.1.linux-amd64.tar.gz \
  /tmp/go.tar.gz
RUN mkdir -p /opt/go/go1.27.1 \
  && tar -xzf /tmp/go.tar.gz --strip-components=1 -C /opt/go/go1.27.1 \
  && rm /tmp/go.tar.gz

# ----------------------------------- LLVM -----------------------------------
FROM docker.io/debian:stable-slim AS stage_llvm
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends xz-utils \
  && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:b5ed9675149cc837c282e9b6962c276c9fa62863d5b2f91537b60848552995b7 \
  https://github.com/llvm/llvm-project/releases/download/llvmorg-23.1.2/LLVM-23.1.2-Linux-X64.tar.xz \
  /tmp/llvm.tar.xz
RUN mkdir -p /opt/llvm/llvm23.1.2 \
  && tar -xJf /tmp/llvm.tar.xz --strip-components=1 -C /opt/llvm/llvm23.1.2 \
  && rm /tmp/llvm.tar.xz

# ----------------------------------- Java -----------------------------------
FROM docker.io/debian:stable-slim AS stage_java
ADD --checksum=sha256:9c70e102f527ac674ac2fe9c7d47b9a04e2d19842ba5ab8e9b33f368bbadfaea \
  https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u504-b01/OpenJDK8U-jdk_x64_linux_hotspot_8u504b01.tar.gz \
  /tmp/openjdk8.tar.gz
ADD --checksum=sha256:1cf69a4848ffb728b3b260dfd45206a51566ab571a02a30092271d4c580bccbc \
  https://github.com/adoptium/temurin27-binaries/releases/download/jdk-27%2B35/OpenJDK27U-jdk_x64_linux_hotspot_27_35.tar.gz \
  /tmp/openjdk27.tar.gz
RUN mkdir -p /opt/java/openjdk8 /opt/java/openjdk27 \
  && tar -xzf /tmp/openjdk8.tar.gz --strip-components=1 -C /opt/java/openjdk8 \
  && tar -xzf /tmp/openjdk27.tar.gz --strip-components=1 -C /opt/java/openjdk27 \
  && rm /tmp/openjdk8.tar.gz /tmp/openjdk27.tar.gz

# ---------------------------------- Node.js ---------------------------------
FROM docker.io/debian:stable-slim AS stage_node
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends libatomic1 patchelf xz-utils \
  && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6 \
  https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-x64.tar.xz \
  /tmp/node24.tar.xz
ADD --checksum=sha256:ca70e9e349de048b9522abb3adc05b3bd6f43c5ffd3ec57916c7da292f59f022 \
  https://nodejs.org/dist/v26.10.0/node-v26.10.0-linux-x64.tar.xz \
  /tmp/node26.tar.xz
RUN mkdir -p /opt/node/nodejs24 /opt/node/nodejs26 \
  && tar -xJf /tmp/node24.tar.xz --strip-components=1 -C /opt/node/nodejs24 \
  && tar -xJf /tmp/node26.tar.xz --strip-components=1 -C /opt/node/nodejs26 \
  && mkdir -p /opt/node/nodejs26/lib \
  && cp -L /usr/lib/x86_64-linux-gnu/libatomic.so.1 /opt/node/nodejs26/lib/ \
  && patchelf --set-rpath '$ORIGIN/../lib' /opt/node/nodejs26/bin/node \
  && rm /tmp/node24.tar.xz /tmp/node26.tar.xz

# ----------------------------------- CUDA -----------------------------------
# CUDA 12.2 is the newest toolkit supported by the target Host's 535 driver.
FROM docker.io/nvidia/cuda:12.2.2-devel-ubuntu22.04 AS stage_cuda

# ----------------------------- Nsight Systems -------------------------------
FROM nvcr.io/nvidia/devtools/nsight-systems-cli:2026.3.1-ubuntu22.04 AS stage_nsys

# --------------------------------- Payload ----------------------------------
FROM docker.io/debian:stable-slim AS resource
COPY --from=stage_rust /opt/rust /opt/resource/opt/rust
COPY --from=stage_go /opt/go /opt/resource/opt/go
COPY --from=stage_llvm /opt/llvm /opt/resource/opt/llvm
COPY --from=stage_cuda /usr/local/cuda-12.2 /opt/resource/usr/local/cuda-12.2
COPY --from=stage_cuda /opt/nvidia/nsight-compute /opt/resource/opt/nvidia/nsight-compute
COPY --from=stage_nsys /opt/nvidia/nsight-systems-cli /opt/resource/opt/nvidia/nsight-systems-cli
COPY --from=stage_sb /usr/local/store /opt/resource/usr/local/store
COPY --from=stage_sb /usr/local/profile/go /opt/resource/usr/local/profile/go
COPY --from=stage_java /opt/java /opt/resource/opt/java
COPY --from=stage_node /opt/node /opt/resource/opt/node
RUN /opt/resource/opt/go/go1.27.1/bin/go version \
  && /opt/resource/opt/llvm/llvm23.1.2/bin/clang --version \
  && /opt/resource/opt/java/openjdk8/bin/java -version \
  && /opt/resource/opt/java/openjdk27/bin/java -version \
  && /opt/resource/opt/node/nodejs24/bin/node --version \
  && /opt/resource/opt/node/nodejs26/bin/node --version
