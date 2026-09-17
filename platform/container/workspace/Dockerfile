# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=debian:13

################################ stage/static tools ################################
FROM docker.io/debian:latest AS stage_sb
RUN apt-get update -y && apt-get install -y curl zstd

COPY platform/container/workspace/config/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml \
  && ln -s -r /opt/bm/bin/bazelisk /opt/bm/bin/bazel \
  && rm -rf /opt/bm/store/nettools/bin/hostname

################################# stage/conda environ ################################
FROM docker.io/debian:stable-slim AS stage_conda

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl -fsSL -o /tmp/miniconda.sh \
    "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-$(uname -m).sh" \
  && bash /tmp/miniconda.sh -b -u -p /opt/conda \
  && /opt/conda/bin/conda clean -afy \
  && rm -rf /tmp/miniconda.sh /var/lib/apt/lists/*

COPY platform/container/workspace/scripts/install-conda-environment.sh /opt/conda/condabin/install-conda-environment

################################# stage/rust ################################
FROM docker.io/debian:stable-slim AS stage_rust
ENV CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup
ENV PATH=/opt/rust/cargo/bin:${PATH}
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl https://sh.rustup.rs -sSf | sh -s -- -y --profile default --no-modify-path --default-toolchain stable \
  && rustup component remove rust-docs \
  && rm -rf /var/lib/apt/lists/*

################################# stage/python ################################
FROM docker.io/debian:stable-slim AS stage_python
COPY --from=stage_sb /opt/bm/bin/uv /usr/local/bin/uv
ENV UV_TOOL_DIR=/opt/uv/tools \
  UV_TOOL_BIN_DIR=/opt/uv/bin \
  UV_PYTHON_INSTALL_DIR=/opt/uv/python \
  UV_PYTHON_BIN_DIR=/opt/uv/bin
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates \
  && uv python install --no-bin 3.9 3.10 3.11 3.12 3.13 3.14 \
  && mkdir -p /opt/uv/bin \
  && ln -s "$(uv python find --managed-python 3.14)" /opt/uv/bin/python3 \
  && uv tool install licenseheaders \
  && uv tool install copyparty \
  && uv tool install dool \
  && uv tool install netron \
  && uv tool install git-filter-repo \
  && uv tool install tensorboard --python 3.12 --with tensorboard-plugin-profile --with "setuptools==81.0.0" \
  && rm -rf /var/lib/apt/lists/*

################################# stage/nix ################################
FROM docker.io/debian:stable-slim AS stage_nix
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl xz-utils \
  && useradd --create-home --uid 5230 --user-group x \
  && rm -rf /var/lib/apt/lists/*

RUN mkdir -m 0755 /nix && chown 5230:5230 /nix

COPY --chown=5230:5230 platform/container/workspace/rootfs/home/x/.config/nixpkgs/config.nix /home/x/.config/nixpkgs/config.nix

USER x
ENV PATH=${PATH}:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin
RUN export NIX_CONFIG='filter-syscalls = false' \
  && curl -fsSL https://nixos.org/nix/install | sh -s -- --no-daemon \
  && nix-channel --add https://nixos.org/channels/nixpkgs-unstable nixpkgs \
  && nix-channel --add https://nixos.org/channels/nixos-25.05 nixpkgs_2505 \
  && nix-channel --update \
  && nix-env -iA nixpkgs.ollama-cpu nixpkgs.lemminx nixpkgs.codex \
    nixpkgs.ghidra nixpkgs.markdownlint-cli2 nixpkgs.pnpm \
    nixpkgs.prettier -p /nix/var/nix/profiles/default \
  # setup java
  && nix-env -iA nixpkgs.maven -p /nix/var/nix/profiles/default \
  && nix-env -iA nixpkgs.jdk8_headless -p /nix/var/nix/profiles/jdk8 \
  && nix-env -iA nixpkgs.jdk25_headless -p /nix/var/nix/profiles/jdk25 \
  # setup nodejs
  && nix-env -iA nixpkgs.nodejs_24 -p /nix/var/nix/profiles/default \
  && nix-env -iA nixpkgs.nodejs_24 -p /nix/var/nix/profiles/nodejs-24 \
  && nix-env -iA nixpkgs.nodejs_26 -p /nix/var/nix/profiles/nodejs-26 \
  # setup go
  && nix-env -iA nixpkgs.go_1_26 -p /nix/var/nix/profiles/default \
  && nix-env -iA nixpkgs.go_1_26 -p /nix/var/nix/profiles/go-1_26 \
  # setup gcc
  && nix-env -iA nixpkgs_2505.gcc12 -p /nix/var/nix/profiles/gcc-12 \
  && nix-env -iA nixpkgs.gcc15 -p /nix/var/nix/profiles/default \
  && nix-env -iA nixpkgs.gcc16 -p /nix/var/nix/profiles/gcc-16 \
  # setup clang
  && nix-env -iA nixpkgs.clang_21 -p /nix/var/nix/profiles/clang-21 \
  && nix-collect-garbage -d \
  && nix-store --optimise

################################# stage/cuda ################################
# 仅作为 CUDA toolkit 的搬运源：官方 devel 镜像把整套 CUDA 装在 /usr/local/cuda-12.2，
# 与发行版无关，故只 COPY 该目录而不 FROM 继承。版本锁定 12.2.2 以匹配 H100 上
# 535 系列驱动（driver 支持上限 CUDA 12.2），避免 runtime 版本超出驱动。
FROM docker.io/nvidia/cuda:12.2.2-devel-ubuntu22.04 AS stage_cuda

################################ stage/nsight systems ################################
FROM nvcr.io/nvidia/devtools/nsight-systems-cli:2026.3.1-ubuntu22.04 AS stage_nsys

################################ stage/vscode extensions ################################
FROM docker.io/debian:stable-slim AS stage_vscode_ext

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl jq \
  && rm -rf /var/lib/apt/lists/*

COPY platform/container/workspace/config/extensions.txt /tmp/extensions.txt
COPY platform/container/workspace/scripts/install-editor-extensions.sh /tmp/install-editor-extensions.sh
RUN bash /tmp/install-editor-extensions.sh /tmp/extensions.txt /opt/editor-extensions

################################ main ################################
FROM docker.io/$BASE_IMAGE AS workspace

ENV PATH=/opt/bm/bin:${PATH}

COPY --link --chown=5230:5230 --from=stage_sb /opt/bm /opt/bm
COPY --link --chown=5230:5230 --from=stage_nix /nix /nix
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-profile /home/x/.nix-profile
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-defexpr /home/x/.nix-defexpr
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-channels /home/x/.nix-channels
COPY --link --chown=5230:5230 --from=stage_rust /opt/rust /opt/rust
COPY --link --chown=5230:5230 --from=stage_python /opt/uv /opt/uv
COPY --link --chown=5230:5230 --from=stage_conda /opt/conda /opt/conda
COPY --link --chown=5230:5230 --from=stage_cuda /usr/local/cuda-12.2 /usr/local/cuda-12.2
COPY --link --chown=5230:5230 --from=stage_cuda /opt/nvidia/nsight-compute /opt/nvidia/nsight-compute
COPY --link --chown=5230:5230 --from=stage_nsys /opt/nvidia/nsight-systems-cli /opt/nvidia/nsight-systems-cli
RUN ln -s cuda-12.2 /usr/local/cuda && ln -s cuda-12.2 /usr/local/cuda-12
COPY --link --chown=5230:5230 --from=stage_vscode_ext /opt/editor-extensions /opt/codespace/share/editor-extensions

COPY platform/container/workspace/rootfs/ /
RUN --mount=type=bind,source=platform/container/workspace/scripts/configure-system.sh,target=/tmp/configure-system.sh \
  bash /tmp/configure-system.sh
RUN --mount=type=bind,source=platform/container/workspace/scripts/install-s6.sh,target=/tmp/install-s6.sh \
  bash /tmp/install-s6.sh

USER x
COPY --chown=5230:5230 platform/container/workspace/agent/ /opt/codespace/agent/
RUN UV_LINK_MODE=copy uv sync --project /opt/codespace/agent --locked --no-dev --python 3.14
RUN git clone --depth=1 https://github.com/curoky/agent-playbook /tmp/agent-playbook \
  && HOME=/home/x bash /tmp/agent-playbook/install.sh \
  && rm -rf /tmp/agent-playbook

RUN sudo chown 5230:5230 /opt

RUN --mount=type=bind,source=platform/container/workspace/tests,target=/opt/codespace/tests,ro \
  python3 -B /opt/codespace/tests/test_image.py

ENTRYPOINT ["/etc/s6/init/bin/init"]
