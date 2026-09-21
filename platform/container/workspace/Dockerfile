# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=debian:13

# --------------------------- Standalone binaries ----------------------------
FROM docker.io/debian:latest AS stage_sb
RUN apt-get update -y && apt-get install -y curl zstd

COPY platform/container/workspace/config/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /usr/local/bin \
  && /usr/local/bin/bm sync /tmp/binman.yaml \
  && ln -s -r /usr/local/bin/bazelisk /usr/local/bin/bazel \
  && rm -rf /usr/local/store/nettools/bin/hostname

# ---------------------------------- Conda -----------------------------------
FROM docker.io/debian:stable-slim AS stage_conda

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl -fsSL -o /tmp/miniconda.sh \
    "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-$(uname -m).sh" \
  && bash /tmp/miniconda.sh -b -u -p /opt/conda \
  && /opt/conda/bin/conda clean -afy \
  && rm -rf /tmp/miniconda.sh /var/lib/apt/lists/*

COPY platform/container/workspace/scripts/install-conda-environment.sh /opt/conda/condabin/install-conda-environment

# ----------------------------------- Rust -----------------------------------
FROM docker.io/debian:stable-slim AS stage_rust
ENV CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup
ENV PATH=/opt/rust/cargo/bin:${PATH}
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl https://sh.rustup.rs -sSf | sh -s -- -y --profile default --no-modify-path --default-toolchain stable \
  && rustup component remove rust-docs \
  && rm -rf /var/lib/apt/lists/*

# ---------------------------------- Python ----------------------------------
FROM docker.io/debian:stable-slim AS stage_python
COPY --from=stage_sb /usr/local/store/uv/bin/uv /usr/local/bin/uv
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
  && uv tool install netron \
  && uv tool install tensorboard --python 3.12 --with tensorboard-plugin-profile --with "setuptools==81.0.0" \
  && rm -rf /var/lib/apt/lists/*

# ----------------------------------- Nix ------------------------------------
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
  && nix-channel --add https://nixos.org/channels/nixpkgs-unstable nixpkgs_unstable \
  && nix-channel --add https://nixos.org/channels/nixos-26.05 nixpkgs \
  && nix-channel --add https://nixos.org/channels/nixos-25.05 nixpkgs_2505 \
  && nix-channel --update \
  && nix-env -iA nixpkgs.ollama-cpu nixpkgs.lemminx nixpkgs_unstable.codex \
    nixpkgs.ghidra nixpkgs.markdownlint-cli2 nixpkgs.pnpm \
    nixpkgs.prettier nixpkgs.mitmproxy \
    nixpkgs.copyparty nixpkgs.dool nixpkgs.git-filter-repo \
    -p /nix/var/nix/profiles/default \
  && nix-env -iA nixpkgs.maven -p /nix/var/nix/profiles/default \
  && nix-env -iA nixpkgs.jdk8_headless -p /nix/var/nix/profiles/jdk8 \
  && nix-env -iA nixpkgs.jdk25_headless -p /nix/var/nix/profiles/jdk25 \
  && nix-env -iA nixpkgs.nodejs_24 -p /nix/var/nix/profiles/default \
  && nix-env -iA nixpkgs.nodejs_24 -p /nix/var/nix/profiles/nodejs-24 \
  && nix-env -iA nixpkgs.nodejs_26 -p /nix/var/nix/profiles/nodejs-26 \
  && nix-env -iA nixpkgs.go_1_26 -p /nix/var/nix/profiles/default \
  && nix-env -iA nixpkgs.go_1_26 -p /nix/var/nix/profiles/go-1_26 \
  && nix-env -iA nixpkgs_2505.gcc12 -p /nix/var/nix/profiles/gcc-12 \
  && nix-env -iA nixpkgs.gcc15 -p /nix/var/nix/profiles/default \
  && nix-env -iA nixpkgs.gcc16 -p /nix/var/nix/profiles/gcc-16 \
  && nix-env -iA nixpkgs.clang_21 -p /nix/var/nix/profiles/clang-21 \
  && nix-collect-garbage -d \
  && nix-store --optimise

# ----------------------------------- CUDA -----------------------------------
# CUDA 12.2 is the newest toolkit supported by the target Host's 535 driver.
FROM docker.io/nvidia/cuda:12.2.2-devel-ubuntu22.04 AS stage_cuda

# ----------------------------- Nsight Systems -------------------------------
FROM nvcr.io/nvidia/devtools/nsight-systems-cli:2026.3.1-ubuntu22.04 AS stage_nsys

# ---------------------------- Editor extensions -----------------------------
FROM docker.io/debian:stable-slim AS stage_vscode_ext

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl jq \
  && rm -rf /var/lib/apt/lists/*

COPY platform/container/workspace/config/extensions.txt /tmp/extensions.txt
COPY platform/container/workspace/scripts/install-editor-extensions.sh /tmp/install-editor-extensions.sh
RUN bash /tmp/install-editor-extensions.sh /tmp/extensions.txt /opt/editor-extensions

# --------------------------------- Runtime ----------------------------------
FROM docker.io/$BASE_IMAGE AS workspace

ENV CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes \
  PATH=/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin

COPY --link --from=stage_sb /usr/local /usr/local
COPY --link --chown=5230:5230 --from=stage_nix /nix /nix
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-defexpr /home/x/.nix-defexpr
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-channels /home/x/.nix-channels
COPY --link --chown=5230:5230 --from=stage_rust /opt/rust /opt/rust
COPY --link --chown=5230:5230 --from=stage_python /opt/uv /opt/uv
COPY --link --chown=5230:5230 --from=stage_conda /opt/conda /opt/conda
COPY --link --from=stage_cuda /usr/local/cuda-12.2 /usr/local/cuda-12.2
COPY --link --chown=5230:5230 --from=stage_cuda /opt/nvidia/nsight-compute /opt/nvidia/nsight-compute
COPY --link --chown=5230:5230 --from=stage_nsys /opt/nvidia/nsight-systems-cli /opt/nvidia/nsight-systems-cli
RUN ln -s cuda-12.2 /usr/local/cuda && ln -s cuda-12.2 /usr/local/cuda-12
COPY --link --from=stage_vscode_ext /opt/editor-extensions /usr/local/codespace/share/editor-extensions

COPY platform/container/workspace/rootfs/ /
RUN --mount=type=bind,source=platform/container/workspace/scripts/configure-system.sh,target=/tmp/configure-system.sh \
  bash /tmp/configure-system.sh
RUN --mount=type=bind,source=platform/container/workspace/scripts/install-s6.sh,target=/tmp/install-s6.sh \
  bash /tmp/install-s6.sh

USER x
COPY --chown=5230:5230 platform/container/workspace/agent/ /usr/local/codespace/agent/
ENV PATH=/opt/bm/bin:/opt/rust/cargo/bin:/opt/uv/bin:/opt/conda/condabin:/nix/var/nix/profiles/default/bin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin
RUN UV_LINK_MODE=copy uv sync --project /usr/local/codespace/agent --locked --no-dev --python 3.14 \
  && git clone --depth=1 https://github.com/curoky/agent-playbook /tmp/agent-playbook \
  && HOME=/home/x bash /tmp/agent-playbook/install.sh \
  && rm -rf /tmp/agent-playbook

RUN ln -s /nix/var/nix/profiles/default /home/x/.nix-profile
USER root
RUN chown -R root:root /usr/local/codespace

# ----------------------------------- Test -----------------------------------
FROM workspace AS test

ENV PATH=/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin
RUN sshd -t \
  && test "$(passwd -S root | awk '{print $2}')" = L \
  && test "$(passwd -S x | awk '{print $2}')" = L \
  && id -nG x | tr ' ' '\n' | grep -Fx sudo \
  && test "$PATH" = /usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin
USER x
ENV PATH=/opt/bm/bin:/opt/rust/cargo/bin:/opt/uv/bin:/opt/conda/condabin:/nix/var/nix/profiles/default/bin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin
RUN --mount=type=bind,source=platform/container/workspace/tests,target=/usr/local/codespace/tests,ro \
  /opt/uv/bin/python3 -B /usr/local/codespace/tests/test_image.py \
  && touch /tmp/image-tested

# --------------------------------- Release ----------------------------------
FROM workspace AS release

COPY --from=test /tmp/image-tested /usr/local/codespace/.image-tested

USER root
ENV PATH=/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/bin:/sbin
ENTRYPOINT ["/etc/s6/init/bin/init"]
