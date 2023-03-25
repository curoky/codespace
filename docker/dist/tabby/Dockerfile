ARG CUDA_VERSION=12.2.2
ARG BASE_CUDA_DEV_CONTAINER=nvidia/cuda:${CUDA_VERSION}-devel-ubuntu22.04
ARG BASE_CUDA_RUN_CONTAINER=nvidia/cuda:${CUDA_VERSION}-runtime-ubuntu22.04

FROM ${BASE_CUDA_DEV_CONTAINER} AS build

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        pkg-config \
        libssl-dev \
        protobuf-compiler \
        git \
        cmake \
        && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# setup rust.
RUN curl https://sh.rustup.rs -sSf | bash -s -- --default-toolchain stable -y
ENV PATH="/root/.cargo/bin:${PATH}" LD_LIBRARY_PATH="/usr/local/cuda/compat/:${LD_LIBRARY_PATH}"

WORKDIR /root/workspace

RUN git clone --recurse-submodules -b v0.25.1 --depth=1 https://github.com/TabbyML/tabby /root/workspace \
  && mkdir -p target

RUN ls -la /root/workspace/docker/Dockerfile.cuda
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/root/workspace/target \
  cargo build --no-default-features --features cuda,prod --release --package tabby \
  && mkdir -p /opt/tabby/bin \
  && cp target/release/llama-server /opt/tabby/bin/ \
  && cp target/release/tabby /opt/tabby/bin/

FROM ${BASE_CUDA_RUN_CONTAINER} AS runtime

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git   \
        curl  \
        unzip \
        openssh-client \
        ca-certificates \
        libgomp1 \
        sudo \
        && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# setup user
RUN useradd --create-home --uid 5230 --user-group x \
  && echo "x:123456" | chpasswd \
  && usermod -aG sudo x \
  && echo "x ALL=(ALL:ALL) NOPASSWD:ALL" >>/etc/sudoers.d/nopasswd_user

RUN mkdir -p /data /opt && chown x:x -R /data /opt

USER x
WORKDIR /home/x

COPY --from=build /opt/tabby /opt/tabby

ENV PATH="$PATH:/opt/tabby/bin"
ENV TABBY_ROOT=/data
ENV RUST_BACKTRACE=1 COLORBT_SHOW_HIDDEN=1 RUST_BACKTRACE=full TABBY_DISABLE_USAGE_COLLECTION=1

ENTRYPOINT ["/opt/tabby/bin/tabby"]
