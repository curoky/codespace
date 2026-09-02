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
# rustup 装到自包含的 /opt/rust，与 main 的 nix/python 步骤并行构建；rust 工具链改动
# 不再让下游 nix/python/conda/Workspace 层失效。
FROM docker.io/debian:stable-slim AS stage_rust
ENV CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup
ENV PATH=/opt/rust/cargo/bin:${PATH}
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl https://sh.rustup.rs -sSf | sh -s -- -y --profile default --no-modify-path --default-toolchain stable \
  && rustup component remove rust-docs \
  && rm -rf /var/lib/apt/lists/*

################################ stage/vscode extensions ################################
# 只依赖 extensions.txt 与安装脚本，与 rust/nix/python 步骤并行构建；无关的仓库
# 改动不再触发几分钟的扩展重装。throwaway 的 code-server 二进制留在本 stage 不入 final image。
FROM docker.io/debian:stable-slim AS stage_vscode_ext

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*

COPY platform/container/workspace/config/extensions.txt /tmp/extensions.txt
COPY platform/container/workspace/scripts/install-editor-extensions.sh /tmp/install-editor-extensions.sh
RUN bash /tmp/install-editor-extensions.sh /tmp/extensions.txt /opt/editor-extensions

################################ main ################################
FROM docker.io/$BASE_IMAGE

ENV PATH=${PATH}:/opt/bm/bin \
  DEBIAN_FRONTEND=noninteractive

ARG BASE_IMAGE
COPY platform/container/workspace/scripts/configure-apt.sh /tmp/configure-apt.sh
RUN /tmp/configure-apt.sh "${BASE_IMAGE}" \
  && apt-get update -y && apt-get install -y sudo locales ca-certificates

# Static tools and Workspace rootfs must be present before configure-system.sh.
COPY --link --chown=5230:5230 --from=stage_sb /opt/bm /opt/bm
COPY platform/container/workspace/rootfs/ /

COPY platform/container/workspace/scripts/configure-system.sh /tmp/configure-system.sh
COPY platform/container/workspace/scripts/install-s6.sh /tmp/install-s6.sh
RUN /tmp/configure-system.sh \
  && chown 5230:5230 /opt \
  && chown -R 5230:5230 /home/x /opt/codespace \
  && chmod -R +x /opt/codespace/bin \
  && /tmp/install-s6.sh \
  && ln -s /opt/bm/store/zsh/bin/zsh /usr/bin \
  && ln -s /opt/bm/store/wget/bin/wget /usr/bin \
  && ln -s /opt/bm/store/less/bin/less /usr/bin \
  && ln -s /opt/bm/store/xz/bin/xz /usr/bin \
  && ln -s /opt/bm/store/git/bin/git /usr/bin \
  && ln -s /opt/bm/store/openssh_gssapi/bin/ssh /usr/bin

# Agent runtime and immutable templates use a product-owned prefix; no source
# checkout is embedded in the image.
COPY --chown=5230:5230 platform/container/workspace/agent/ /opt/codespace/agent/

USER x

# setup nixpkgs
ENV PATH=${PATH}:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin
# Nix's seccomp BPF filter cannot load under buildx's QEMU arm64 emulation.
# Keep the override local to this build layer rather than the final image.
RUN export NIX_CONFIG='filter-syscalls = false' \
  && curl -fsSL https://nixos.org/nix/install | sh -s -- --no-daemon \
  && nix-channel --add https://nixos.org/channels/nixpkgs-unstable nixpkgs \
  && nix-channel --update \
  && nix-env -iA nixpkgs.ollama-cpu nixpkgs.lemminx nixpkgs.codex \
  # setup java
  && nix-env -iA nixpkgs.maven \
  && nix-env -iA nixpkgs.jdk8_headless -p /nix/var/nix/profiles/jdk8 \
  && nix-env -iA nixpkgs.jdk25_headless -p /nix/var/nix/profiles/jdk25 \
  # setup nodejs
  && nix-env -iA nixpkgs.nodejs_24 \
  && nix-env -iA nixpkgs.nodejs_24 -p /nix/var/nix/profiles/nodejs-24 \
  # setup go
  && nix-env -iA nixpkgs.go_1_26 \
  && nix-env -iA nixpkgs.go_1_26 -p /nix/var/nix/profiles/go-1_26 \
  # setup gcc
  && nix-env -iA nixpkgs.gcc15 \
  && nix-collect-garbage -d \
  && nix-store --optimise

# setup rust
# COPY 放在 nix 之后：rust 工具链改动不会让上面昂贵的 nix 层失效。
ENV CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup
ENV PATH=${PATH}:/opt/rust/cargo/bin
COPY --link --chown=5230:5230 --from=stage_rust /opt/rust /opt/rust

# setup python & tools
# uv 的成果物统一落到 /opt/uv：cache-dir 由 system 级 /etc/uv/uv.toml 固定（唯一
# 支持写进配置文件的目录项，由 Workspace rootfs 烤入）；tool/python 的安装目录 uv
# 没有对应 setting，只能用 UV_* ENV。ENV 与配置同层可靠，且被烤进后续所有层。
ENV UV_TOOL_DIR=/opt/uv/tools \
  UV_TOOL_BIN_DIR=/opt/uv/bin \
  UV_PYTHON_INSTALL_DIR=/opt/uv/python \
  UV_PYTHON_BIN_DIR=/opt/uv/bin
ENV PATH=${PATH}:/opt/uv/bin
RUN uv python install --no-bin 3.9 3.10 3.11 3.12 3.13 3.14
RUN uv tool install licenseheaders \
  && uv tool install tensorboard --python 3.12 --with tensorboard-plugin-profile --with "setuptools==81.0.0"

# setup conda
COPY --link --chown=5230:5230 --from=stage_conda /opt/conda /opt/conda
ENV PATH=${PATH}:/opt/conda/condabin
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main \
  && conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# setup Workspace Agent
RUN UV_LINK_MODE=copy uv sync --project /opt/codespace/agent --locked --no-dev --python 3.14

# setup Trae user rules
RUN git clone --depth=1 https://github.com/curoky/agent-playbook /tmp/agent-playbook \
  && HOME=/home/x bash /tmp/agent-playbook/install.sh \
  && rm -rf /tmp/agent-playbook

# Editor Remote 扩展参考副本（stage_vscode_ext 并行构建），运行期由 init-home 播种。
COPY --link --chown=5230:5230 --from=stage_vscode_ext /opt/editor-extensions /opt/codespace/share/editor-extensions

USER root

ENV PATH=${PATH}:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec
ENTRYPOINT ["/etc/s6/init/bin/init"]
