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
  && bash /tmp/miniconda.sh -b -u -p /home/x/.local/opt/conda \
  && /home/x/.local/opt/conda/bin/conda clean -afy

COPY platform/container/workspace/scripts/install-conda-environment.sh /home/x/.local/opt/conda/condabin/install-conda-environment

# ----------------------------------- Rust -----------------------------------
FROM docker.io/debian:stable-slim AS stage_rust
ENV CARGO_HOME=/home/x/.local/opt/rust/cargo RUSTUP_HOME=/home/x/.local/opt/rust/rustup
ENV PATH=/home/x/.local/opt/rust/cargo/bin:${PATH}
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates curl \
  && curl https://sh.rustup.rs -sSf | bash -s -- -y --profile minimal --no-modify-path --default-toolchain 1.100.0 \
  && rustup component add clippy rustfmt rust-src rust-analyzer llvm-tools

# ------------------------------------ Go ------------------------------------
FROM docker.io/debian:stable-slim AS stage_go
ADD --checksum=sha256:7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840 \
  https://go.dev/dl/go1.27.4.linux-amd64.tar.gz \
  /tmp/go.tar.gz
RUN mkdir -p /home/x/.local/opt/go/go1.27.4 \
  && tar -xzf /tmp/go.tar.gz --strip-components=1 -C /home/x/.local/opt/go/go1.27.4 \
  && ln -s go1.27.4 /home/x/.local/opt/go/go1.27

# --------------------------- Workspace executables --------------------------
FROM docker.io/golang:1.27.4 AS stage_workspace_tools
ENV CGO_ENABLED=0
WORKDIR /src
COPY platform/container/workspace/go.mod platform/container/workspace/go.sum ./
RUN go mod download
COPY platform/container/workspace/agent/ ./agent/
COPY platform/container/workspace/tools/node-tool/ ./tools/node-tool/
COPY platform/container/workspace/tools/java-tool/ ./tools/java-tool/
RUN go build -mod=readonly -trimpath -o /out/node-tool ./tools/node-tool \
  && go build -mod=readonly -trimpath -o /out/java-tool ./tools/java-tool \
  && go build -mod=readonly -trimpath -o /out/workspace-agent ./agent

# ------------------------- Codex LLMBox Provider -----------------------------
FROM docker.io/golang:1.27.4 AS stage_codex_llmbox_provider
ENV CGO_ENABLED=0
WORKDIR /src
COPY platform/container/workspace/tools/codex-llmbox-provider/go.mod platform/container/workspace/tools/codex-llmbox-provider/go.sum ./
RUN go mod download
COPY platform/container/workspace/tools/codex-llmbox-provider/src/ ./src/
RUN go build -mod=readonly -trimpath -o /home/x/.local/opt/codex_llmbox_provider/bin/codex-llmbox-provider ./src

# ----------------------------------- Java -----------------------------------
FROM docker.io/debian:stable-slim AS stage_java
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates
ADD --checksum=sha256:27eda854481d20806d918b30cdd417c6bed4fd15882e24f3595dc8ae7fb5d095 \
  https://github.com/adoptium/temurin8-binaries/releases/download/jdk8u514-b01/OpenJDK8U-jdk_x64_linux_hotspot_8u514b01.tar.gz \
  /tmp/openjdk8.tar.gz
ADD --checksum=sha256:005e57ee860978acfeeff1be2b30f770664fe2b941e9b803c61c76992086d107 \
  https://github.com/adoptium/temurin27-binaries/releases/download/jdk-27.0.1.1%2B4/OpenJDK27U-jdk_x64_linux_hotspot_27.0.1.1_4.tar.gz \
  /tmp/openjdk27.tar.gz
RUN mkdir -p /home/x/.local/opt/java/openjdk8 /home/x/.local/opt/java/openjdk27 \
  && tar -xzf /tmp/openjdk8.tar.gz --strip-components=1 -C /home/x/.local/opt/java/openjdk8 \
  && tar -xzf /tmp/openjdk27.tar.gz --strip-components=1 -C /home/x/.local/opt/java/openjdk27

ADD --checksum=sha256:52005a6a0783dee2fd324aea1cc7cc29e6239a700f2eea94f9dd685d072e3491 \
  https://github.com/coursier/coursier/releases/download/v2.1.27/cs-x86_64-pc-linux-static.gz \
  /tmp/cs.gz
RUN gzip -dc /tmp/cs.gz > /home/x/.local/opt/java/cs \
  && chmod 0755 /home/x/.local/opt/java/cs

ENV HOME=/home/x PATH=/home/x/.local/opt/java:${PATH}
COPY --from=stage_workspace_tools /out/java-tool /home/x/.local/opt/java/java-tool
RUN java-tool \
    install maven@3.9.16 org.apache.maven:apache-maven:3.9.16 \
    --extract --type zip --classifier bin \
    --executable mvn=bin/mvn --executable mvnDebug=bin/mvnDebug \
    --executable mvnyjp=bin/mvnyjp --inherit-java \
  && java-tool \
    install lemminx@0.31.2 org.eclipse.lemminx:org.eclipse.lemminx:0.31.2 \
    --repository https://repo.eclipse.org/content/repositories/lemminx-releases/ \
    --main lemminx=org.eclipse.lemminx.XMLServerLauncher

# ---------------------------------- Python ----------------------------------
FROM docker.io/debian:stable-slim AS stage_python
COPY --from=stage_sb /usr/local/store/uv/bin/uv /usr/local/bin/uv
ENV UV_TOOL_DIR=/home/x/.local/opt/uv/tools \
  UV_TOOL_BIN_DIR=/home/x/.local/opt/uv/bin \
  UV_PYTHON_INSTALL_DIR=/home/x/.local/opt/uv/python \
  UV_PYTHON_BIN_DIR=/home/x/.local/opt/uv/bin
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates \
  && uv python install --default 3.15.2 \
  && uv tool install copyparty --python "$UV_PYTHON_BIN_DIR/python3.15" \
  && uv tool install licenseheaders --python "$UV_PYTHON_BIN_DIR/python3.15" \
  && uv tool install netron --python "$UV_PYTHON_BIN_DIR/python3.15" \
  && uv tool install mitmproxy --python "$UV_PYTHON_BIN_DIR/python3.15" \
  && uv tool install git-filter-repo --python "$UV_PYTHON_BIN_DIR/python3.15" \
  && uv tool install dool --python "$UV_PYTHON_BIN_DIR/python3.15"

# ---------------------------------- Node.js ---------------------------------
FROM stage_python AS stage_node
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends ca-certificates libatomic1 patchelf xz-utils
ADD --checksum=sha256:4f2b175a6d53a5c617a80dba2676238a0688cef28c6da4eba35c7d844e66fcfb \
  https://nodejs.org/dist/v24.22.3/node-v24.22.3-linux-x64.tar.xz \
  /tmp/node24.tar.xz
ADD --checksum=sha256:5c063e46bab0fbc1c17cc445d7ff129cbdcd0471be6ed83b6ab864f8143bc864 \
  https://nodejs.org/dist/v26.13.1/node-v26.13.1-linux-x64.tar.xz \
  /tmp/node26.tar.xz
RUN mkdir -p /home/x/.local/opt/node/nodejs24 /home/x/.local/opt/node/nodejs26/lib /home/x/.local/opt/node/tools/bin \
  && tar -xJf /tmp/node24.tar.xz --strip-components=1 -C /home/x/.local/opt/node/nodejs24 \
  && tar -xJf /tmp/node26.tar.xz --strip-components=1 -C /home/x/.local/opt/node/nodejs26 \
  && cp -L /usr/lib/x86_64-linux-gnu/libatomic.so.1 /home/x/.local/opt/node/nodejs26/lib/ \
  && patchelf --set-rpath '$ORIGIN/../lib' /home/x/.local/opt/node/nodejs26/bin/node

COPY --from=stage_sb /usr/local/store/pnpm/bin/pnpm /usr/local/bin/pnpm
ENV HOME=/home/x PATH=/home/x/.local/opt/node:${PATH}
COPY --from=stage_workspace_tools /out/node-tool /home/x/.local/opt/node/node-tool
RUN node-tool install defuddle@0.19.4 \
  && node-tool install markdownlint-cli2@0.23.3 \
  && node-tool install prettier@3.9.9

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
    nixpkgs_unstable.codex nixpkgs_unstable.claude-code \
    nixpkgs_unstable.xvfb nixpkgs_unstable.xvfb-run nixpkgs_unstable.chromium \
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
  && nix-env -iA nixpkgs.gcc16 -p /nix/var/nix/profiles/default \
  # && nix-env -iA nixpkgs.clang_21 -p /nix/var/nix/profiles/clang-21 \
  && nix-collect-garbage -d \
  && nix-store --optimise

# --------------------------------- Runtime ----------------------------------
FROM docker.io/$BASE_IMAGE AS workspace

COPY platform/container/workspace/rootfs/ /
RUN chown -hR 5230:5230 /home/x

COPY --link --from=stage_sb /usr/local /usr/local
COPY --chown=5230:5230 --from=stage_workspace_tools /out/workspace-agent /opt/codespace-agent/workspace-agent
RUN --mount=type=bind,source=platform/container/workspace/scripts/configure-system.sh,target=/tmp/configure-system.sh \
  bash /tmp/configure-system.sh

COPY --link --chown=5230:5230 --from=stage_nix /nix /nix
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-defexpr /home/x/.nix-defexpr
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.nix-channels /home/x/.nix-channels
COPY --link --chown=5230:5230 --from=stage_nix /home/x/.local/state/nix /home/x/.local/state/nix
COPY --link --chown=5230:5230 --from=stage_python /home/x/.local/opt/uv /home/x/.local/opt/uv
COPY --link --chown=5230:5230 --from=stage_conda /home/x/.local/opt/conda /home/x/.local/opt/conda
COPY --link --chown=5230:5230 --from=stage_node /home/x/.local/opt/node /home/x/.local/opt/node
COPY --link --chown=5230:5230 --from=stage_go /home/x/.local/opt/go /home/x/.local/opt/go
COPY --link --chown=5230:5230 --from=stage_rust /home/x/.local/opt/rust /home/x/.local/opt/rust
COPY --link --chown=5230:5230 --from=stage_java /home/x/.local/opt/java /home/x/.local/opt/java
COPY --link --chown=5230:5230 --from=stage_codex_llmbox_provider /home/x/.local/opt/codex_llmbox_provider /home/x/.local/opt/stage_codex_llmbox_provider
COPY --link --from=stage_nvidia_container_toolkit /opt/nvidia-container-toolkit/ /opt/nvidia/nvidia-container-toolkit/

RUN --mount=type=bind,source=platform/container/workspace/scripts/install-s6.sh,target=/tmp/install-s6.sh \
  bash /tmp/install-s6.sh

USER x
RUN git clone --depth=1 https://github.com/curoky/agent-playbook /tmp/agent-playbook \
  && bash /tmp/agent-playbook/install.sh \
  && rm -rf /tmp/agent-playbook

USER root
ENTRYPOINT ["/etc/s6/init/bin/init"]
