# syntax=docker/dockerfile:1.9.0

# ----------------------------------- Rust -----------------------------------
FROM docker.io/debian:stable-slim AS stage_rust
ENV CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup
ENV PATH=/opt/rust/cargo/bin:${PATH}
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl https://sh.rustup.rs -sSf | sh -s -- -y --profile default --no-modify-path --default-toolchain stable \
  && rustup component remove rust-docs

# ---------------------------------- Binman ----------------------------------
FROM docker.io/debian:latest AS stage_bm
RUN apt-get update -y && apt-get install -y curl

RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /usr/local

# ---------------------------- Binman packages -------------------------------
FROM stage_bm AS stage_sb
COPY platform/container/workspace/config/binman-resource.yaml /tmp/binman.yaml
RUN /usr/local/bin/bm --prefix /usr/local install --file /tmp/binman.yaml \
  && rm -f /usr/local/bin/bm \
  && find /usr/local/store -type d -exec chmod 0755 {} +

# ------------------------------ Build tools ---------------------------------
FROM stage_bm AS stage_build_tools
RUN /usr/local/bin/bm --prefix /usr/local install --no-link uv pnpm

# ------------------------------------ Go ------------------------------------
FROM docker.io/debian:stable-slim AS stage_go
ADD --checksum=sha256:63d339f0da5ab53635a56f2490a7984dfe12dfcff22ad749f63edaf590168445 \
  https://go.dev/dl/go1.27.1.linux-amd64.tar.gz \
  /tmp/go.tar.gz
RUN mkdir -p /opt/go/go1.27.1 \
  && tar -xzf /tmp/go.tar.gz --strip-components=1 -C /opt/go/go1.27.1

# ----------------------------------- LLVM -----------------------------------
FROM docker.io/debian:stable-slim AS stage_llvm
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends xz-utils
ADD --checksum=sha256:b5ed9675149cc837c282e9b6962c276c9fa62863d5b2f91537b60848552995b7 \
  https://github.com/llvm/llvm-project/releases/download/llvmorg-23.1.2/LLVM-23.1.2-Linux-X64.tar.xz \
  /tmp/llvm.tar.xz
RUN mkdir -p /opt/llvm/llvm23.1.2 \
  && tar -xJf /tmp/llvm.tar.xz --strip-components=1 -C /opt/llvm/llvm23.1.2

# ---------------------------------- Python ----------------------------------
FROM docker.io/debian:stable-slim AS stage_python
COPY --from=stage_build_tools /usr/local/store/uv/bin/uv /usr/local/bin/uv
ENV UV_TOOL_DIR=/opt/resource/opt/uv/tools \
  UV_TOOL_BIN_DIR=/opt/resource/opt/uv/bin \
  UV_PYTHON_INSTALL_DIR=/opt/resource/opt/uv/python \
  UV_PYTHON_BIN_DIR=/opt/resource/opt/uv/bin
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates \
  && uv python install --no-bin 3.9 3.10 3.11 3.12 3.13 3.14 \
  && uv tool install licenseheaders \
    --python /opt/resource/opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 \
  && uv tool install netron \
    --python /opt/resource/opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 \
  && uv tool install mitmproxy \
    --python /opt/resource/opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 \
  && uv tool install dool \
    --python /opt/resource/opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 \
  && uv tool install git-filter-repo \
    --python /opt/resource/opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 \
  && uv tool install tensorboard \
    --python /opt/resource/opt/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12 \
    --with tensorboard-plugin-profile --with "setuptools==81.0.0"

# ----------------------------------- Java -----------------------------------
FROM docker.io/debian:stable-slim AS stage_java
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates
ADD --checksum=sha256:9c70e102f527ac674ac2fe9c7d47b9a04e2d19842ba5ab8e9b33f368bbadfaea \
  https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u504-b01/OpenJDK8U-jdk_x64_linux_hotspot_8u504b01.tar.gz \
  /tmp/openjdk8.tar.gz
ADD --checksum=sha256:1cf69a4848ffb728b3b260dfd45206a51566ab571a02a30092271d4c580bccbc \
  https://github.com/adoptium/temurin27-binaries/releases/download/jdk-27%2B35/OpenJDK27U-jdk_x64_linux_hotspot_27_35.tar.gz \
  /tmp/openjdk27.tar.gz
RUN mkdir -p /opt/java/openjdk8 /opt/java/openjdk27 \
  && tar -xzf /tmp/openjdk8.tar.gz --strip-components=1 -C /opt/java/openjdk8 \
  && tar -xzf /tmp/openjdk27.tar.gz --strip-components=1 -C /opt/java/openjdk27

ADD --checksum=sha256:80ffca22aed9e8b9713a232f3394fd81d7f20322df75efdb2b047dbd3e3a23bb \
  https://downloads.apache.org/maven/maven-3/3.9.16/binaries/apache-maven-3.9.16-bin.tar.gz \
  /tmp/apache-maven.tar.gz
ADD --checksum=sha256:f4fde164e785c635e5f86361dbf4b993bfe2c5f83fdb52891d058b7dfc9bcfc8 \
  https://download.eclipse.org/lemminx/releases/0.31.2/org.eclipse.lemminx-uber.jar \
  /tmp/lemminx.jar
ADD --checksum=sha256:ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db \
  https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip \
  /tmp/ghidra.zip

COPY --from=stage_build_tools /usr/local/store/uv/bin/uv /usr/local/bin/uv
COPY platform/container/workspace/tools/java-tool/ /tmp/java-tool/
RUN /tmp/java-tool/java-tool \
    install maven@3.9.16 /tmp/apache-maven.tar.gz --extract \
    --executable mvn=bin/mvn --executable mvnDebug=bin/mvnDebug \
    --executable mvnyjp=bin/mvnyjp --java /opt/java/openjdk27 \
  && /tmp/java-tool/java-tool \
    install lemminx@0.31.2 /tmp/lemminx.jar \
    --jar lemminx=lemminx.jar --java /opt/java/openjdk27 \
  && /tmp/java-tool/java-tool \
    install ghidra@12.1.4 /tmp/ghidra.zip --extract \
    --executable ghidra=ghidraRun --executable-dir ghidra-=support \
    --java /opt/java/openjdk27

# ---------------------------------- Node.js ---------------------------------
FROM docker.io/debian:stable-slim AS stage_node
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates libatomic1 patchelf xz-utils
ADD --checksum=sha256:fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6 \
  https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-x64.tar.xz \
  /tmp/node24.tar.xz
ADD --checksum=sha256:ca70e9e349de048b9522abb3adc05b3bd6f43c5ffd3ec57916c7da292f59f022 \
  https://nodejs.org/dist/v26.10.0/node-v26.10.0-linux-x64.tar.xz \
  /tmp/node26.tar.xz
RUN mkdir -p /opt/node/nodejs24 /opt/node/nodejs26/lib /opt/node/tools/bin \
  && tar -xJf /tmp/node24.tar.xz --strip-components=1 -C /opt/node/nodejs24 \
  && tar -xJf /tmp/node26.tar.xz --strip-components=1 -C /opt/node/nodejs26 \
  && cp -L /usr/lib/x86_64-linux-gnu/libatomic.so.1 /opt/node/nodejs26/lib/ \
  && patchelf --set-rpath '$ORIGIN/../lib' /opt/node/nodejs26/bin/node

COPY --from=stage_build_tools /usr/local/store/uv/bin/uv /usr/local/bin/uv
COPY --from=stage_build_tools /usr/local/store/pnpm/bin/pnpm /usr/local/bin/pnpm
COPY platform/container/workspace/tools/node-tool/ /tmp/node-tool/
RUN /tmp/node-tool/node-tool \
    install defuddle@0.19.4 \
    --node /opt/node/nodejs24 --pnpm /usr/local/bin/pnpm \
  && /tmp/node-tool/node-tool \
    install markdownlint-cli2@0.23.3 \
    --node /opt/node/nodejs24 --pnpm /usr/local/bin/pnpm \
  && /tmp/node-tool/node-tool \
    install prettier@3.9.9 \
    --node /opt/node/nodejs24 --pnpm /usr/local/bin/pnpm

# ----------------------------------- CUDA -----------------------------------
# CUDA 12.2 is the newest toolkit supported by the target Host's 535 driver.
FROM docker.io/nvidia/cuda:12.2.2-devel-ubuntu22.04 AS stage_cuda

# ----------------------------- Nsight Systems -------------------------------
FROM nvcr.io/nvidia/devtools/nsight-systems-cli:2026.3.1-ubuntu22.04 AS stage_nsys

# --------------------------------- Payload ----------------------------------
FROM docker.io/debian:stable-slim AS payload
COPY --from=stage_rust /opt/rust /opt/resource/opt/rust
COPY --from=stage_go /opt/go /opt/resource/opt/go
COPY --from=stage_llvm /opt/llvm /opt/resource/opt/llvm
COPY --from=stage_cuda /usr/local/cuda-12.2 /opt/resource/usr/local/cuda-12.2
COPY --from=stage_cuda /opt/nvidia/nsight-compute /opt/resource/opt/nvidia/nsight-compute
COPY --from=stage_nsys /opt/nvidia/nsight-systems-cli /opt/resource/opt/nvidia/nsight-systems-cli
COPY --from=stage_sb /usr/local/bin /opt/resource/usr/local/bin
COPY --from=stage_sb /usr/local/store /opt/resource/usr/local/store
COPY --from=stage_sb /usr/local/profile /opt/resource/usr/local/profile
COPY --from=stage_java /opt/java /opt/resource/opt/java
COPY --from=stage_node /opt/node /opt/resource/opt/node
COPY --from=stage_python /opt/resource/opt/uv /opt/resource/opt/uv

# ----------------------------------- Test -----------------------------------
FROM payload AS test
USER 5230:5230
RUN /opt/resource/opt/go/go1.27.1/bin/go version \
  && /opt/resource/opt/llvm/llvm23.1.2/bin/clang --version \
  && test ! -e /opt/resource/usr/local/bin/bm \
  && /opt/resource/usr/local/bin/radare2 -v \
  && /opt/resource/usr/local/bin/rizin -v \
  # && /opt/resource/usr/local/profile/clang-tools/bin/clang-format --version \
  # && /opt/resource/usr/local/profile/nodejs/bin/node --version \
  # && /opt/resource/usr/local/profile/protobuf/bin/protoc --version \
  # && /opt/resource/usr/local/profile/python/bin/python3 --version \
  && /opt/resource/opt/java/openjdk8/bin/java -version \
  && /opt/resource/opt/java/openjdk27/bin/java -version \
  && test -x /opt/resource/opt/java/tools/bin/mvn \
  && test -r /opt/resource/opt/java/tools/envs/lemminx/payload/lemminx.jar \
  && test -x /opt/resource/opt/java/tools/envs/ghidra/payload/ghidraRun \
  && /opt/resource/opt/node/nodejs24/bin/node --version \
  && /opt/resource/opt/node/nodejs26/bin/node --version \
  && test ! -e /opt/resource/usr/local/bin/uv \
  && test ! -e /opt/resource/usr/local/bin/pnpm \
  && test ! -e /opt/resource/opt/uv/bin/uv \
  && test ! -e /opt/resource/opt/node/tools/bin/pnpm \
  && test ! -e /opt/resource/usr/local/store/uv \
  && test ! -e /opt/resource/usr/local/store/pnpm \
  && test -x /opt/resource/opt/node/tools/bin/defuddle \
  && test -x /opt/resource/opt/node/tools/bin/markdownlint-cli2 \
  && test -x /opt/resource/opt/node/tools/bin/prettier \
  && /opt/resource/opt/uv/python/cpython-3.9-linux-x86_64-gnu/bin/python3.9 --version \
  && /opt/resource/opt/uv/python/cpython-3.10-linux-x86_64-gnu/bin/python3.10 --version \
  && /opt/resource/opt/uv/python/cpython-3.11-linux-x86_64-gnu/bin/python3.11 --version \
  && /opt/resource/opt/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12 --version \
  && /opt/resource/opt/uv/python/cpython-3.13-linux-x86_64-gnu/bin/python3.13 --version \
  && /opt/resource/opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 --version \
  && test -x /opt/resource/opt/uv/bin/licenseheaders \
  && test -x /opt/resource/opt/uv/bin/netron \
  && test -x /opt/resource/opt/uv/bin/mitmproxy \
  && test -x /opt/resource/opt/uv/bin/dool \
  && test -x /opt/resource/opt/uv/bin/git-filter-repo \
  && test -x /opt/resource/opt/uv/bin/tensorboard

# --------------------------------- Resource ---------------------------------
FROM test AS resource
USER root
