# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=debian:13

# --------------------------- Standalone binaries ----------------------------
FROM docker.io/debian:latest AS stage_sb
RUN apt-get update -y && apt-get install -y curl

COPY platform/container/workspace/config/binman.yaml /tmp/binman.yaml
# Some packages expose sbin as a symlink to bin; preserve Debian's real directory after linking.
RUN rmdir /usr/local/sbin \
  && curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /usr/local \
  && /usr/local/bin/bm --prefix /usr/local install --file /tmp/binman.yaml \
  && rm -f /usr/local/sbin \
  && install -d /usr/local/sbin \
  && ln -s -r /usr/local/bin/bazelisk /usr/local/bin/bazel \
  && rm -rf /usr/local/store/nettools/bin/hostname \
  && rm -rf /usr/local/store/bazelisk/bin/sha256sum \
  && find /usr/local/store -type d -exec chmod 0755 {} +

# ---------------------------------- Conda -----------------------------------
FROM docker.io/debian:stable-slim AS stage_conda

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl -fsSL -o /tmp/miniconda.sh \
    "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-$(uname -m).sh" \
  && bash /tmp/miniconda.sh -b -u -p /opt/conda \
  && /opt/conda/bin/conda clean -afy

COPY platform/container/workspace/scripts/install-conda-environment.sh /opt/conda/condabin/install-conda-environment

# ----------------------------------- Rust -----------------------------------
FROM docker.io/debian:stable-slim AS stage_rust
ENV CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup
ENV PATH=/opt/rust/cargo/bin:${PATH}
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl https://sh.rustup.rs -sSf | bash -s -- -y --profile default --no-modify-path --default-toolchain stable \
  && rustup component add rust-src rust-analyzer llvm-tools \
  && rustup component remove rust-docs

# ------------------------------------ Go ------------------------------------
FROM docker.io/debian:stable-slim AS stage_go
ADD --checksum=sha256:63d339f0da5ab53635a56f2490a7984dfe12dfcff22ad749f63edaf590168445 \
  https://go.dev/dl/go1.27.1.linux-amd64.tar.gz \
  /tmp/go.tar.gz
RUN mkdir -p /opt/go/go1.27.1 \
  && tar -xzf /tmp/go.tar.gz --strip-components=1 -C /opt/go/go1.27.1

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

# ---------------------------------- Python ----------------------------------
FROM docker.io/debian:stable-slim AS stage_python
COPY --from=stage_sb /usr/local/store/uv/bin/uv /usr/local/bin/uv
ENV UV_TOOL_DIR=/opt/uv/tools \
  UV_TOOL_BIN_DIR=/opt/uv/bin \
  UV_PYTHON_INSTALL_DIR=/opt/uv/python \
  UV_PYTHON_BIN_DIR=/opt/uv/bin
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates \
  && uv python install 3.14 \
  && uv tool install copyparty \
    --python /opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 \
  && uv tool install licenseheaders \
    --python /opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 \
  && uv tool install netron \
    --python /opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 \
  && uv tool install mitmproxy \
    --python /opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 \
  && uv tool install dool \
    --python /opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 \
  && uv tool install git-filter-repo \
    --python /opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14

# ---------------------------------- Node.js ---------------------------------
FROM stage_python AS stage_node
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

COPY --from=stage_sb /usr/local/store/pnpm/bin/pnpm /usr/local/bin/pnpm
COPY platform/container/workspace/tools/node-tool/ /tmp/node-tool/
RUN /tmp/node-tool/node-tool init \
  && /tmp/node-tool/node-tool install defuddle@0.19.4 \
    --node /opt/node/nodejs24 --pnpm /usr/local/bin/pnpm \
  && /tmp/node-tool/node-tool install markdownlint-cli2@0.23.3 \
    --node /opt/node/nodejs24 --pnpm /usr/local/bin/pnpm \
  && /tmp/node-tool/node-tool install prettier@3.9.9 \
    --node /opt/node/nodejs24 --pnpm /usr/local/bin/pnpm

# ------------------------- NVIDIA Container Toolkit ------------------------
FROM docker.io/debian:stable-slim AS stage_nvidia_container_toolkit
ADD --checksum=sha256:14dc22489851d4f1a6d1bbfdfb51524c8f110091738570cddaddc09778a63ad9 \
  https://github.com/NVIDIA/nvidia-container-toolkit/releases/download/v1.20.1/nvidia-container-toolkit_1.20.1_deb_amd64.tar.gz \
  /tmp/nvidia-container-toolkit.tar.gz
RUN tar -xzf /tmp/nvidia-container-toolkit.tar.gz -C /tmp \
  && install -d /opt/nvidia-container-toolkit \
  && dpkg-deb --fsys-tarfile \
    /tmp/release-v1.20.1-stable/packages/ubuntu18.04/amd64/nvidia-container-toolkit-base_1.20.1-1_amd64.deb \
    | tar -x -C /opt/nvidia-container-toolkit --strip-components=3 \
      ./usr/bin/nvidia-ctk \
      ./usr/bin/nvidia-cdi-hook

# ----------------------------------- Nix ------------------------------------
FROM docker.io/debian:stable-slim AS stage_nix
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl xz-utils \
  && useradd --create-home --uid 5230 --user-group x

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
    # nixpkgs.mitmproxy nixpkgs.copyparty nixpkgs.dool nixpkgs.git-filter-repo \
    # nixpkgs.lemminx nixpkgs.ghidra nixpkgs.maven \
    nixpkgs_unstable.codex \
    # nixpkgs.markdownlint-cli2 nixpkgs.pnpm nixpkgs.prettier \
    -p /nix/var/nix/profiles/default \
  # && nix-env -iA nixpkgs.jdk8_headless -p /nix/var/nix/profiles/jdk8 \
  # && nix-env -iA nixpkgs.jdk25_headless -p /nix/var/nix/profiles/jdk25 \
  # && nix-env -iA nixpkgs.nodejs_24 -p /nix/var/nix/profiles/default \
  # && nix-env -iA nixpkgs.nodejs_24 -p /nix/var/nix/profiles/nodejs-24 \
  # && nix-env -iA nixpkgs.nodejs_26 -p /nix/var/nix/profiles/nodejs-26 \
  # && nix-env -iA nixpkgs.go_1_26 -p /nix/var/nix/profiles/default \
  # && nix-env -iA nixpkgs.go_1_26 -p /nix/var/nix/profiles/go-1_26 \
  # && nix-env -iA nixpkgs_2505.gcc12 -p /nix/var/nix/profiles/gcc-12 \
  && nix-env -iA nixpkgs.gcc15 -p /nix/var/nix/profiles/default \
  # && nix-env -iA nixpkgs.gcc16 -p /nix/var/nix/profiles/gcc-16 \
  # && nix-env -iA nixpkgs.clang_21 -p /nix/var/nix/profiles/clang-21 \
  && nix-collect-garbage -d \
  && nix-store --optimise

# --------------------------------- Runtime ----------------------------------
FROM docker.io/$BASE_IMAGE AS workspace

COPY platform/container/workspace/rootfs/ /
RUN mkdir -p /opt/java /opt/node \
  && chown -hR 5230:5230 /home/x /opt/java /opt/node /opt/uv

COPY --link --from=stage_sb /usr/local /usr/local
COPY --chown=5230:5230 platform/container/workspace/tools/node-tool/ /opt/node/node-tool/
COPY --chown=5230:5230 platform/container/workspace/tools/java-tool/ /opt/java/java-tool/
RUN --mount=type=bind,source=platform/container/workspace/scripts/configure-system.sh,target=/tmp/configure-system.sh \
  bash /tmp/configure-system.sh

COPY --link --chown=5230:5230 --from=stage_nix /nix /nix
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-defexpr /home/x/.nix-defexpr
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-channels /home/x/.nix-channels
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.local/state/nix /home/x/.local/state/nix
COPY --link --chown=5230:5230 --from=stage_python /opt/uv /opt/uv
COPY --link --chown=5230:5230 --from=stage_conda /opt/conda /opt/conda
COPY --link --chown=5230:5230 --from=stage_node /opt/node /opt/node
COPY --link --chown=5230:5230 --from=stage_go /opt/go /opt/go
COPY --link --chown=5230:5230 --from=stage_rust /opt/rust /opt/rust
COPY --link --chown=5230:5230 --from=stage_java /opt/java /opt/java
COPY --link --from=stage_nvidia_container_toolkit /opt/nvidia-container-toolkit/ /opt/nvidia/nvidia-container-toolkit/

RUN --mount=type=bind,source=platform/container/workspace/scripts/install-s6.sh,target=/tmp/install-s6.sh \
  bash /tmp/install-s6.sh

USER x
COPY --chown=5230:5230 platform/container/workspace/agent/ /opt/codespace-agent/
RUN /opt/java/java-tool/java-tool init \
  && /opt/node/node-tool/node-tool init \
  && UV_LINK_MODE=copy /usr/local/bin/uv sync --project /opt/codespace-agent --locked --no-dev \
    --python /opt/uv/python/cpython-3.14-linux-x86_64-gnu/bin/python3.14 \
  && git clone --depth=1 https://github.com/curoky/agent-playbook /tmp/agent-playbook \
  && HOME=/home/x bash /tmp/agent-playbook/install.sh \
  && rm -rf /tmp/agent-playbook

USER root
ENTRYPOINT ["/etc/s6/init/bin/init"]
