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
  && rm -rf /usr/local/store/nettools/bin/hostname \
  && find /usr/local/store -type d -exec chmod 0755 {} +

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
  # && nix-channel --add https://nixos.org/channels/nixos-25.05 nixpkgs_2505 \
  && nix-channel --update \
  && nix-env -iA \
    # nixpkgs.ollama-cpu
    nixpkgs.lemminx nixpkgs_unstable.codex \
    nixpkgs.ghidra nixpkgs.markdownlint-cli2 nixpkgs.pnpm \
    nixpkgs.prettier nixpkgs.mitmproxy \
    nixpkgs.copyparty nixpkgs.dool nixpkgs.git-filter-repo \
    -p /nix/var/nix/profiles/default \
  && nix-env -iA nixpkgs.maven -p /nix/var/nix/profiles/default \
  && nix-env -iA nixpkgs.jdk8_headless -p /nix/var/nix/profiles/jdk8 \
  && nix-env -iA nixpkgs.jdk25_headless -p /nix/var/nix/profiles/jdk25 \
  && nix-env -iA nixpkgs.nodejs_24 -p /nix/var/nix/profiles/default \
  # && nix-env -iA nixpkgs.nodejs_24 -p /nix/var/nix/profiles/nodejs-24 \
  # && nix-env -iA nixpkgs.nodejs_26 -p /nix/var/nix/profiles/nodejs-26 \
  && nix-env -iA nixpkgs.go_1_26 -p /nix/var/nix/profiles/default \
  # && nix-env -iA nixpkgs.go_1_26 -p /nix/var/nix/profiles/go-1_26 \
  # && nix-env -iA nixpkgs_2505.gcc12 -p /nix/var/nix/profiles/gcc-12 \
  && nix-env -iA nixpkgs.gcc15 -p /nix/var/nix/profiles/default \
  # && nix-env -iA nixpkgs.gcc16 -p /nix/var/nix/profiles/gcc-16 \
  && nix-env -iA nixpkgs.clang_21 -p /nix/var/nix/profiles/clang-21 \
  && nix-collect-garbage -d \
  && nix-store --optimise

# --------------------------------- Runtime ----------------------------------
FROM docker.io/$BASE_IMAGE AS workspace

COPY --link --from=stage_sb /usr/local /usr/local
COPY --link --chown=5230:5230 --from=stage_nix /nix /nix
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-defexpr /home/x/.nix-defexpr
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-channels /home/x/.nix-channels
COPY --link --chown=5230:5230 --from=stage_python /opt/uv /opt/uv
COPY --link --chown=5230:5230 --from=stage_conda /opt/conda /opt/conda

RUN ln -s /opt/resource/opt/rust /opt/rust \
  && ln -s /opt/resource/usr/local/cuda-12.2 /usr/local/cuda-12.2 \
  && ln -s /opt/resource/opt/nvidia /opt/nvidia \
  && ln -s /opt/resource/usr/local/store/radare2 /usr/local/store/radare2 \
  && ln -s /opt/resource/usr/local/store/rizin /usr/local/store/rizin \
  && ln -s /opt/resource/usr/local/profile/go /usr/local/profile/go

COPY platform/container/workspace/rootfs/ /
RUN --mount=type=bind,source=platform/container/workspace/scripts/configure-system.sh,target=/tmp/configure-system.sh \
  bash /tmp/configure-system.sh
RUN --mount=type=bind,source=platform/container/workspace/scripts/install-s6.sh,target=/tmp/install-s6.sh \
  bash /tmp/install-s6.sh

USER x
COPY --chown=5230:5230 platform/container/workspace/agent/ /opt/codespace-agent/
RUN UV_LINK_MODE=copy uv sync --project /opt/codespace-agent --locked --no-dev --python 3.14 \
  && git clone --depth=1 https://github.com/curoky/agent-playbook /tmp/agent-playbook \
  && HOME=/home/x bash /tmp/agent-playbook/install.sh \
  && rm -rf /tmp/agent-playbook

RUN ln -s /nix/var/nix/profiles/default /home/x/.nix-profile

USER root
ENV CONDA_PLUGINS_AUTO_ACCEPT_TOS=yes
ENTRYPOINT ["/etc/s6/init/bin/init"]
