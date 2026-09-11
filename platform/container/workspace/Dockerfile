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
# 在独立 stage 中生成自包含的 Rust toolchain，避免耦合 main stage 的其他 toolchain。
FROM docker.io/debian:stable-slim AS stage_rust
ENV CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup
ENV PATH=/opt/rust/cargo/bin:${PATH}
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl https://sh.rustup.rs -sSf | sh -s -- -y --profile default --no-modify-path --default-toolchain stable \
  && rustup component remove rust-docs \
  && rm -rf /var/lib/apt/lists/*

################################# stage/python ################################
# 独立生成 /opt/uv 下的 Python 与 uv tools，避免占用 main stage 构建层。
# uv 二进制复用 stage_sb 的 binman 版本；tool/python 目录只能通过 UV_* 配置。
FROM docker.io/debian:stable-slim AS stage_python
COPY --from=stage_sb /opt/bm/bin/uv /usr/local/bin/uv
ENV UV_TOOL_DIR=/opt/uv/tools \
  UV_TOOL_BIN_DIR=/opt/uv/bin \
  UV_PYTHON_INSTALL_DIR=/opt/uv/python \
  UV_PYTHON_BIN_DIR=/opt/uv/bin
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates \
  && uv python install --no-bin 3.9 3.10 3.11 3.12 3.13 3.14 \
  && uv tool install licenseheaders \
  && uv tool install copyparty \
  && uv tool install dool \
  && uv tool install netron \
  && uv tool install git-filter-repo \
  && uv tool install tensorboard --python 3.12 --with tensorboard-plugin-profile --with "setuptools==81.0.0" \
  && rm -rf /var/lib/apt/lists/*

################################# stage/nix ################################
# 在独立 stage 生成 /nix 与 per-user profiles，避免每次改动 main 其他层都重跑耗时的
# nix 安装；产物保持 nix 默认单用户布局，由 main stage 整体 COPY。
FROM docker.io/debian:stable-slim AS stage_nix
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl xz-utils \
  && useradd --create-home --uid 5230 --user-group x \
  && rm -rf /var/lib/apt/lists/*

# 预创建 /nix 并归属 x：single-user installer 仅在 /nix 缺失时用 sudo 创建它，
# 而本 stage 无 sudo。提前建好可让安装器直接跳过该步。
RUN mkdir -m 0755 /nix && chown 5230:5230 /nix

# unfree 包（如 codex）与 nix.conf 必须在安装期可见，否则 nix-env -iA 失败。
COPY --chown=5230:5230 platform/container/workspace/rootfs/home/x/.config/nixpkgs/config.nix /home/x/.config/nixpkgs/config.nix
COPY platform/container/workspace/rootfs/etc/nix/nix.conf /etc/nix/nix.conf

USER x
ENV PATH=${PATH}:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin
# Nix's seccomp BPF filter cannot load under buildx's QEMU arm64 emulation.
# Keep the override local to this build layer rather than the final image.
RUN export NIX_CONFIG='filter-syscalls = false' \
  && curl -fsSL https://nixos.org/nix/install | sh -s -- --no-daemon \
  && nix-channel --add https://nixos.org/channels/nixpkgs-unstable nixpkgs \
  # gcc12 已在 25.11 起从 unstable 移除，锁定仍含 gcc12 的 25.05 channel 单独供其使用。
  && nix-channel --add https://nixos.org/channels/nixos-25.05 nixpkgs_2505 \
  && nix-channel --update \
  && nix-env -iA nixpkgs.ollama-cpu nixpkgs.lemminx nixpkgs.codex -p /nix/var/nix/profiles/default \
  # setup formatters & linters
  && nix-env -iA nixpkgs.markdownlint-cli2 nixpkgs.pnpm nixpkgs.prettier -p /nix/var/nix/profiles/default \
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

################################ stage/vscode extensions ################################
# 生成 editor extension template；一次性的 code-server 不进入 final image。
FROM docker.io/debian:stable-slim AS stage_vscode_ext

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl jq \
  && rm -rf /var/lib/apt/lists/*

COPY platform/container/workspace/config/extensions.txt /tmp/extensions.txt
COPY platform/container/workspace/scripts/install-editor-extensions.sh /tmp/install-editor-extensions.sh
RUN bash /tmp/install-editor-extensions.sh /tmp/extensions.txt /opt/editor-extensions

################################ main ################################
# 布局按“稳定性递减”排列：自包含 toolchain（只随各自 stage 变化）在前，随仓库源码
# 变动的 system 配置与 Agent 在后，源码日常改动不再使 toolchain 大层失效。
# 归属在生成时即正确（COPY 用 --chown，写 home 的步骤以 x 身份运行），故不做全树
# recursive chown；末尾只补 COPY 无法表达的两件事：/opt 根可写、bin 执行位。
FROM docker.io/$BASE_IMAGE
ARG BASE_IMAGE

# 环境变量集中声明；PATH 一次拼定，避免层层追加。
ENV DEBIAN_FRONTEND=noninteractive \
  CARGO_HOME=/opt/rust/cargo \
  RUSTUP_HOME=/opt/rust/rustup \
  UV_TOOL_DIR=/opt/uv/tools \
  UV_TOOL_BIN_DIR=/opt/uv/bin \
  UV_PYTHON_INSTALL_DIR=/opt/uv/python \
  UV_PYTHON_BIN_DIR=/opt/uv/bin \
  CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes \
  CUDA_HOME=/usr/local/cuda \
  LD_LIBRARY_PATH=/usr/local/cuda/lib64 \
  PATH=/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin:/opt/rust/cargo/bin:/opt/uv/bin:/opt/conda/condabin:/usr/local/cuda/bin:${PATH}

# Toolchains：均来自独立 stage，与仓库源码解耦。数字 uid 的 --chown 不要求用户先存在。
# nix 保持默认单用户布局，home 下指向 /nix 的 symlink 一并带入；uv 资产统一在 /opt/uv。
COPY --link --chown=5230:5230 --from=stage_sb /opt/bm /opt/bm
COPY --link --chown=5230:5230 --from=stage_nix /nix /nix
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-profile /home/x/.nix-profile
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-defexpr /home/x/.nix-defexpr
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-channels /home/x/.nix-channels
COPY --link --chown=5230:5230 --from=stage_rust /opt/rust /opt/rust
COPY --link --chown=5230:5230 --from=stage_python /opt/uv /opt/uv
COPY --link --chown=5230:5230 --from=stage_conda /opt/conda /opt/conda
# CUDA toolkit：只搬实体目录 /usr/local/cuda-12.2；官方镜像的 cuda/cuda-12 软链走
# alternatives，故在 main stage 重建稳定软链，供 CUDA_HOME 与 PATH 使用。
COPY --link --chown=5230:5230 --from=stage_cuda /usr/local/cuda-12.2 /usr/local/cuda-12.2
RUN ln -s cuda-12.2 /usr/local/cuda && ln -s cuda-12.2 /usr/local/cuda-12
# Editor Remote extension template，运行期由 home-init 播种。
COPY --link --chown=5230:5230 --from=stage_vscode_ext /opt/editor-extensions /opt/codespace/share/editor-extensions

# System：rootfs 就绪后配置系统与编译 s6。configure-system 依赖 /opt/bm 与
# rootfs，install-s6 依赖 s6 profile 与 /etc/s6。
COPY platform/container/workspace/scripts/configure-apt.sh /tmp/configure-apt.sh
RUN /tmp/configure-apt.sh "${BASE_IMAGE}"
COPY platform/container/workspace/rootfs/ /
COPY platform/container/workspace/scripts/configure-system.sh /tmp/configure-system.sh
COPY platform/container/workspace/scripts/install-s6.sh /tmp/install-s6.sh
RUN /tmp/configure-system.sh && /tmp/install-s6.sh

# Agent runtime 与 Trae rules 均以 x 身份生成，产物天生属 5230:5230，无需额外 chown。
# agent 源码改动频繁，故置于 toolchain 之后；uv sync 依赖 /opt/uv 与 agent 源码。
USER x
COPY --chown=5230:5230 platform/container/workspace/agent/ /opt/codespace/agent/
RUN UV_LINK_MODE=copy uv sync --project /opt/codespace/agent --locked --no-dev --python 3.14
# install.sh 靠 $HOME 定位；HOME 只是 build-time 需求，局部注入即可，不渗入镜像
# （运行期各进程自带显式 HOME=/home/x）。
RUN git clone --depth=1 https://github.com/curoky/agent-playbook /tmp/agent-playbook \
  && HOME=/home/x bash /tmp/agent-playbook/install.sh \
  && rm -rf /tmp/agent-playbook

# 仅补 COPY 无法表达的：让 x 可写 /opt 根、补齐 rootfs 无法保留的 bin 执行位。
USER root
RUN chown 5230:5230 /opt && chmod -R +x /opt/codespace/bin

ENTRYPOINT ["/etc/s6/init/bin/init"]
