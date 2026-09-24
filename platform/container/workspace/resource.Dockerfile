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

# ------------------------------------ uv ------------------------------------
FROM ghcr.io/astral-sh/uv:0.12.5 AS stage_uv

# ----------------------------------- Java -----------------------------------
FROM docker.io/debian:stable-slim AS stage_java
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates \
  && rm -rf /var/lib/apt/lists/*
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

ADD --checksum=sha256:80ffca22aed9e8b9713a232f3394fd81d7f20322df75efdb2b047dbd3e3a23bb \
  https://downloads.apache.org/maven/maven-3/3.9.16/binaries/apache-maven-3.9.16-bin.tar.gz \
  /tmp/apache-maven.tar.gz
ADD --checksum=sha256:f4fde164e785c635e5f86361dbf4b993bfe2c5f83fdb52891d058b7dfc9bcfc8 \
  https://download.eclipse.org/lemminx/releases/0.31.2/org.eclipse.lemminx-uber.jar \
  /tmp/lemminx.jar
ADD --checksum=sha256:ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db \
  https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip \
  /tmp/ghidra.zip

COPY --from=stage_uv /uv /usr/local/bin/uv
COPY platform/container/workspace/tools/java-tool/java-tool.py \
  platform/container/workspace/tools/java-tool/java-tool.py.lock \
  /tmp/java-tool/
RUN UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python \
  uv run --locked --script /tmp/java-tool/java-tool.py \
  install maven@3.9.16 /tmp/apache-maven.tar.gz --extract \
  --executable mvn=bin/mvn --executable mvnDebug=bin/mvnDebug \
  --executable mvnyjp=bin/mvnyjp --java /opt/java/openjdk27 \
  && UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python \
  uv run --locked --script /tmp/java-tool/java-tool.py \
  install lemminx@0.31.2 /tmp/lemminx.jar \
  --jar lemminx=lemminx.jar --java /opt/java/openjdk27 \
  && UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python \
  uv run --locked --script /tmp/java-tool/java-tool.py \
  install ghidra@12.1.4 /tmp/ghidra.zip --extract \
  --executable ghidra=ghidraRun --executable-dir ghidra-=support \
  --java /opt/java/openjdk27 \
  && env -u JAVA_HOME PATH=/usr/bin:/bin /opt/java/tools/bin/mvn --version \
  && test -x /opt/java/tools/bin/lemminx \
  && test -x /opt/java/tools/bin/ghidra \
  && rm -rf /tmp/java-tool /tmp/uv-cache /tmp/uv-python \
    /tmp/apache-maven.tar.gz /tmp/lemminx.jar /tmp/ghidra.zip

# ---------------------------------- Node.js ---------------------------------
FROM docker.io/debian:stable-slim AS stage_node
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates libatomic1 patchelf xz-utils \
  && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6 \
  https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-x64.tar.xz \
  /tmp/node24.tar.xz
ADD --checksum=sha256:ca70e9e349de048b9522abb3adc05b3bd6f43c5ffd3ec57916c7da292f59f022 \
  https://nodejs.org/dist/v26.10.0/node-v26.10.0-linux-x64.tar.xz \
  /tmp/node26.tar.xz
ADD --checksum=sha256:2b5f62986b14f2891fb78e5b554e60e38f25987217fed578f0303bbfda5e124a \
  https://registry.npmjs.org/@pnpm/exe.linux-x64/-/exe.linux-x64-12.6.0.tgz \
  /tmp/pnpm.tar.gz
RUN mkdir -p /opt/node/nodejs24 /opt/node/nodejs26 /opt/node/tools/bin /opt/node/tools/lib \
  && tar -xJf /tmp/node24.tar.xz --strip-components=1 -C /opt/node/nodejs24 \
  && tar -xJf /tmp/node26.tar.xz --strip-components=1 -C /opt/node/nodejs26 \
  && tar -xzf /tmp/pnpm.tar.gz --strip-components=1 -C /opt/node/tools/bin package/pnpm \
  && mkdir -p /opt/node/nodejs26/lib \
  && cp -L /usr/lib/x86_64-linux-gnu/libatomic.so.1 /opt/node/nodejs26/lib/ \
  && cp -L /usr/lib/x86_64-linux-gnu/libatomic.so.1 /opt/node/tools/lib/ \
  && patchelf --set-rpath '$ORIGIN/../lib' /opt/node/nodejs26/bin/node \
  && patchelf --set-rpath '$ORIGIN/../lib' /opt/node/tools/bin/pnpm \
  && env PATH=/usr/bin:/bin /opt/node/tools/bin/pnpm --version \
  && rm /tmp/node24.tar.xz /tmp/node26.tar.xz /tmp/pnpm.tar.gz

COPY --from=stage_uv /uv /usr/local/bin/uv
COPY platform/container/workspace/tools/node-tool/node-tool.py \
  platform/container/workspace/tools/node-tool/node-tool.py.lock \
  /tmp/node-tool/
RUN UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python \
  uv run --script /tmp/node-tool/node-tool.py \
  install markdownlint-cli2@0.23.3 \
  --node /opt/node/nodejs24 --pnpm /opt/node/tools/bin/pnpm \
  && UV_CACHE_DIR=/tmp/uv-cache UV_PYTHON_INSTALL_DIR=/tmp/uv-python \
  uv run --script /tmp/node-tool/node-tool.py \
  install prettier@3.9.9 \
  --node /opt/node/nodejs24 --pnpm /opt/node/tools/bin/pnpm \
  && env PATH=/usr/bin:/bin /opt/node/tools/bin/markdownlint-cli2 --version \
  && env PATH=/usr/bin:/bin /opt/node/tools/bin/pnpm --version \
  && env PATH=/usr/bin:/bin /opt/node/tools/bin/prettier --version \
  && rm -rf /tmp/node-tool /tmp/uv-cache /tmp/uv-python

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
