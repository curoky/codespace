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
    # for install gcc
    curl tar ca-certificates dpkg-dev flex gcc g++ file tzdata unzip
    # for install llvm
    # libxml2-dev git

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

RUN mkdir -p /tmp/clang/src \
  && curl -sSL https://github.com/llvm/llvm-project/archive/refs/tags/llvmorg-21.1.0.tar.gz | tar -x --gzip -C /tmp/clang/src --strip-components 1 \
  && cd /tmp/clang/src \
  && mkdir -p /tmp/clang/build && cd /tmp/clang/build \
  && cmake -S "/tmp/clang/src/llvm" -B . \
    -GNinja \
    -DCMAKE_INSTALL_PREFIX="/opt/llvm" \
    -DCMAKE_BUILD_TYPE="Release" \
    -DLLVM_ENABLE_PROJECTS="clang;clang-tools-extra"

RUN cd /tmp/clang/build  \
  && ninja -j "$(nproc)" \
  && rm -rf /tmp/clang

FROM debian:stable-slim

COPY --from=builder /opt/llvm /opt/llvm
