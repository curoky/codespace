# syntax=docker/dockerfile:1.9.0

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
RUN /usr/local/bin/bm --prefix /usr/local install --no-link uv

# ----------------------------------- LLVM -----------------------------------
FROM docker.io/debian:stable-slim AS stage_llvm
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends xz-utils
ADD --checksum=sha256:bd4d1c434ff69ef06d19e7934c04708da677e5f2eb51f5bcf052ab91818f0094 \
  https://github.com/llvm/llvm-project/releases/download/llvmorg-23.1.6/LLVM-23.1.6-Linux-X64.tar.xz \
  /tmp/llvm.tar.xz
RUN mkdir -p /home/x/.local/opt/llvm/llvm23.1.6 \
  && tar -xJf /tmp/llvm.tar.xz --strip-components=1 -C /home/x/.local/opt/llvm/llvm23.1.6 \
  && ln -s llvm23.1.6 /home/x/.local/opt/llvm/llvm23

# ---------------------------------- Python ----------------------------------
FROM docker.io/debian:stable-slim AS stage_python
COPY --from=stage_build_tools /usr/local/store/uv/bin/uv /usr/local/bin/uv
ENV UV_TOOL_DIR=/opt/resource/home/x/.local/opt/uv/tools \
  UV_TOOL_BIN_DIR=/opt/resource/home/x/.local/opt/uv/bin \
  UV_PYTHON_INSTALL_DIR=/opt/resource/home/x/.local/opt/uv/python \
  UV_PYTHON_BIN_DIR=/opt/resource/home/x/.local/opt/uv/bin
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates \
  && uv python install --no-bin 3.9.25 3.10.22 3.11.18 3.12.16 3.13.18 3.14.10 3.15.2 \
  && uv tool install tensorboard \
    --python /opt/resource/home/x/.local/opt/uv/python/cpython-3.12.16-linux-x86_64-gnu/bin/python3.12 \
    --with tensorboard-plugin-profile --with "setuptools==81.0.0"

# ----------------------------------- Java -----------------------------------
FROM docker.io/golang:1.27.4 AS stage_java_tool
WORKDIR /src
COPY platform/container/workspace/go.mod platform/container/workspace/go.sum ./
RUN go mod download
COPY platform/container/workspace/tools/java-tool/ ./tools/java-tool/
RUN CGO_ENABLED=0 go build -mod=readonly -trimpath -o /out/java-tool ./tools/java-tool

FROM docker.io/debian:stable-slim AS stage_java
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates
# java-tool validates the launcher runtime during installation; the JDK is not exported.
ADD --checksum=sha256:005e57ee860978acfeeff1be2b30f770664fe2b941e9b803c61c76992086d107 \
  https://github.com/adoptium/temurin27-binaries/releases/download/jdk-27.0.1.1%2B4/OpenJDK27U-jdk_x64_linux_hotspot_27.0.1.1_4.tar.gz \
  /tmp/openjdk27.tar.gz
RUN mkdir -p /home/x/.local/opt/java/openjdk27 \
  && tar -xzf /tmp/openjdk27.tar.gz --strip-components=1 -C /home/x/.local/opt/java/openjdk27

ADD --checksum=sha256:80ffca22aed9e8b9713a232f3394fd81d7f20322df75efdb2b047dbd3e3a23bb \
  https://downloads.apache.org/maven/maven-3/3.9.16/binaries/apache-maven-3.9.16-bin.tar.gz \
  /tmp/apache-maven.tar.gz
ADD --checksum=sha256:f4fde164e785c635e5f86361dbf4b993bfe2c5f83fdb52891d058b7dfc9bcfc8 \
  https://download.eclipse.org/lemminx/releases/0.31.2/org.eclipse.lemminx-uber.jar \
  /tmp/lemminx.jar
ADD --checksum=sha256:ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db \
  https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip \
  /tmp/ghidra.zip

ENV HOME=/home/x
COPY --from=stage_java_tool /out/java-tool /usr/local/bin/java-tool
RUN java-tool \
    install maven@3.9.16 /tmp/apache-maven.tar.gz --extract \
    --executable mvn=bin/mvn --executable mvnDebug=bin/mvnDebug \
    --executable mvnyjp=bin/mvnyjp --inherit-java \
  && java-tool \
    install lemminx@0.31.2 /tmp/lemminx.jar \
    --jar lemminx=lemminx.jar \
  && java-tool \
    install ghidra@12.1.4 /tmp/ghidra.zip --extract \
    --executable ghidra=ghidraRun --executable-dir ghidra-=support

# ----------------------------------- CUDA -----------------------------------
# CUDA 12.2 is the newest toolkit supported by the target Host's 535 driver.
FROM docker.io/nvidia/cuda:12.2.2-devel-ubuntu22.04 AS stage_cuda

# ----------------------------- Nsight Systems -------------------------------
FROM nvcr.io/nvidia/devtools/nsight-systems-cli:2026.3.1-ubuntu22.04 AS stage_nsys

# --------------------------------- Payload ----------------------------------
FROM docker.io/debian:stable-slim AS payload
COPY --from=stage_llvm /home/x/.local/opt/llvm /opt/resource/home/x/.local/opt/llvm
COPY --from=stage_cuda /usr/local/cuda-12.2 /opt/resource/usr/local/cuda-12.2
COPY --from=stage_cuda /opt/nvidia/nsight-compute /opt/resource/opt/nvidia/nsight-compute
COPY --from=stage_nsys /opt/nvidia/nsight-systems-cli /opt/resource/opt/nvidia/nsight-systems-cli
COPY --from=stage_sb /usr/local/bin /opt/resource/usr/local/bin
COPY --from=stage_sb /usr/local/store /opt/resource/usr/local/store
COPY --from=stage_sb /usr/local/profile /opt/resource/usr/local/profile
COPY --from=stage_java /home/x/.local/opt/java/tools /opt/resource/home/x/.local/opt/java/tools
COPY --from=stage_python /opt/resource/home/x/.local/opt/uv /opt/resource/home/x/.local/opt/uv

# ----------------------------------- Test -----------------------------------
FROM payload AS test
USER 5230:5230
RUN /opt/resource/home/x/.local/opt/llvm/llvm23/bin/clang --version \
  && test ! -e /opt/resource/home/x/.local/opt/go \
  && test ! -e /opt/resource/home/x/.local/opt/rust \
  && test ! -e /opt/resource/home/x/.local/opt/node \
  && test ! -e /opt/resource/home/x/.local/opt/java/openjdk8 \
  && test ! -e /opt/resource/home/x/.local/opt/java/openjdk27 \
  && test ! -e /opt/resource/usr/local/bin/bm \
  && /opt/resource/usr/local/bin/radare2 -v \
  && /opt/resource/usr/local/bin/rizin -v \
  # && /opt/resource/usr/local/profile/clang-tools/bin/clang-format --version \
  # && /opt/resource/usr/local/profile/nodejs/bin/node --version \
  # && /opt/resource/usr/local/profile/protobuf/bin/protoc --version \
  # && /opt/resource/usr/local/profile/python/bin/python3 --version \
  && test -x /opt/resource/home/x/.local/opt/java/tools/bin/mvn \
  && test -r /opt/resource/home/x/.local/opt/java/tools/envs/lemminx/payload/lemminx.jar \
  && test -x /opt/resource/home/x/.local/opt/java/tools/envs/ghidra/payload/ghidraRun \
  && test ! -e /opt/resource/usr/local/bin/uv \
  && test ! -e /opt/resource/usr/local/bin/pnpm \
  && test ! -e /opt/resource/home/x/.local/opt/uv/bin/uv \
  && test ! -e /opt/resource/usr/local/store/uv \
  && test ! -e /opt/resource/usr/local/store/pnpm \
  && /opt/resource/home/x/.local/opt/uv/python/cpython-3.9.25-linux-x86_64-gnu/bin/python3.9 --version \
  && /opt/resource/home/x/.local/opt/uv/python/cpython-3.10.22-linux-x86_64-gnu/bin/python3.10 --version \
  && /opt/resource/home/x/.local/opt/uv/python/cpython-3.11.18-linux-x86_64-gnu/bin/python3.11 --version \
  && /opt/resource/home/x/.local/opt/uv/python/cpython-3.12.16-linux-x86_64-gnu/bin/python3.12 --version \
  && /opt/resource/home/x/.local/opt/uv/python/cpython-3.13.18-linux-x86_64-gnu/bin/python3.13 --version \
  && /opt/resource/home/x/.local/opt/uv/python/cpython-3.14.10-linux-x86_64-gnu/bin/python3.14 --version \
  && /opt/resource/home/x/.local/opt/uv/python/cpython-3.15.2-linux-x86_64-gnu/bin/python3.15 --version \
  && test -x /opt/resource/home/x/.local/opt/uv/bin/tensorboard

# --------------------------------- Resource ---------------------------------
FROM test AS resource
USER root
