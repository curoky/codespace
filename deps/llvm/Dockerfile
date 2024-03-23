# https://github.com/llvm/llvm-project/blob/main/llvm/utils/docker/build_docker_image.sh
# https://github.com/llvm/llvm-project/blob/main/llvm/docs/Docker.rst
# https://llvm.org/docs/Docker.html
# https://llvm.org/docs/AdvancedBuilds.html#bootstrap-builds

FROM debian:buster-backports AS builder
# FROM launcher.gcr.io/google/debian10:latest AS builder

RUN cat /etc/apt/sources.list \
  && sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list \
  && sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list.d/backports.list \
  && sed -i 's/security.debian.org/archive.debian.org/g' /etc/apt/sources.list \
  && sed -i '/stretch-updates/d' /etc/apt/sources.list \
  && apt-get update -y

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    # basic tools
    curl tar unzip ca-certificates file tzdata dpkg-dev \
    # compiler tools
    gcc g++ \
    # for install llvm
    libxml2-dev git

# install latest ninja
RUN curl -sSL -o ninja-linux.zip "https://github.com/ninja-build/ninja/releases/download/v1.12.1/ninja-linux.zip" \
  && unzip ninja-linux.zip -d /usr/local/bin \
  && rm ninja-linux.zip

# install latest cmake
RUN curl -sSL -o cmake.tar.gz "https://github.com/Kitware/CMake/releases/download/v4.1.1/cmake-4.1.1-linux-x86_64.tar.gz" \
  && tar -x --gzip -f cmake.tar.gz -C /usr/local --strip-components 1 \
  && rm cmake.tar.gz

COPY --from=curoky/devspace:deps-python-3.12.11 /opt/python/python-3.12.11 /opt/python/python-3.12.11

ENV PATH=${PATH}:/opt/python/python-3.12.11/bin \
  LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/python/python-3.12.11/lib

ARG LLVM_VERSION 21.1.0

RUN mkdir -p /tmp/llvm/src \
  && curl -sSL https://github.com/llvm/llvm-project/archive/refs/tags/llvmorg-${LLVM_VERSION}.tar.gz | tar -x --gzip -C /tmp/llvm/src --strip-components 1 \
  && cd /tmp/llvm/src \
  && mkdir -p /tmp/llvm/build && cd /tmp/llvm/build

ARG ENABLE_2STAGE=false

RUN [ ${ENABLE_2STAGE} = "true" ] && cd /tmp/llvm/build \
  && cmake -S "/tmp/llvm/src/llvm" -B . \
    -GNinja \
    -DCMAKE_INSTALL_PREFIX="/opt/llvm/llvm-${LLVM_VERSION}" \
    -DCMAKE_BUILD_TYPE="Release" \
    -DLLVM_TARGETS_TO_BUILD=Native \
    -DLLVM_ENABLE_PROJECTS="clang;clang-tools-extra;lld" \
    -DLLVM_ENABLE_RUNTIMES="compiler-rt" \
    -DLLVM_ENABLE_LTO=ON \
    -DCLANG_ENABLE_BOOTSTRAP=ON \
    -DCLANG_BOOTSTRAP_TARGETS="install-clang;install-clang-resource-headers" \
    -DBOOTSTRAP_CMAKE_BUILD_TYPE=Release \
  && cd /tmp/llvm/build \
  && ninja stage2-install-clang stage2-install-clang-resource-headers || echo "Skipping"

RUN [ ${ENABLE_2STAGE} = "false" ] && cd /tmp/llvm/build \
  && cmake -S "/tmp/llvm/src/llvm" -B . \
    -GNinja \
    -DCMAKE_INSTALL_PREFIX="/opt/llvm/llvm-${LLVM_VERSION}" \
    -DCMAKE_BUILD_TYPE="Release" \
    -DLLVM_TARGETS_TO_BUILD=Native \
    -DLLVM_ENABLE_PROJECTS="clang;clang-tools-extra;lld" \
    -DLLVM_ENABLE_RUNTIMES="compiler-rt" \
    -DLLVM_ENABLE_LTO=ON \
    -DBOOTSTRAP_CMAKE_BUILD_TYPE=Release \
  && cd /tmp/llvm/build \
  && ninja install-clang install-clang-resource-headers || echo "Skipping"

FROM debian:stable-slim

COPY --from=builder /opt/llvm /opt/llvm
