# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=debian:13

################################ stage/static tools ################################
FROM docker.io/debian:latest AS stage_sb
RUN apt-get update -y && apt-get install -y curl zstd

COPY codespace/images/dev/script/sb-pkgs.yaml /tmp/sb-pkgs.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/client/install.sh \
    | bash -s -- --prefix /opt/sb/bin \
  && /opt/sb/bin/sb sync /tmp/sb-pkgs.yaml \
  && ln -s -r /opt/sb/bin/bazelisk /opt/sb/bin/bazel \
  && rm -rf /opt/sb/store/nettools/bin/hostname \
  && rm -rf /opt/sb/store/cmake/share/cmake*/Help \
  && rm -rf /opt/sb/store/cmake/share/doc \
  && rm -rf /opt/sb/store/vim/share/vim/vim*/doc \
  && rm -rf /opt/sb/store/protobuf*/lib

################################# stage/conda environ ################################
FROM docker.io/debian:stable-slim AS stage_conda

RUN apt-get update -y \
  && apt-get install -y curl gcc g++ git pkg-config \
  && curl -sSL -o /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
  && bash /tmp/miniconda.sh -b -u -p /opt/conda

COPY codespace/images/dev/script/setup-conda-env.sh /opt/conda/condabin/setup-conda-env.sh

################################ main ################################
FROM docker.io/$BASE_IMAGE

ENV PATH=${PATH}:/opt/sb/bin \
  DEBIAN_FRONTEND=noninteractive \
  SSL_CERT_FILE=/opt/sb/store/cacert/etc/ssl/certs/ca-certificates.crt

ARG BASE_IMAGE
COPY codespace/images/dev/script/patch-apt.sh /tmp/patch-apt.sh
RUN /tmp/patch-apt.sh ${BASE_IMAGE} \
  && apt-get update -y && apt-get install -y sudo locales ca-certificates

# Static tools and system config must be present before setup-sysconf.sh (it
# runs `chsh` to the sb zsh and tightens perms on the rootfs-provided /etc/ssh &
# /etc/sudoers.d files). Lay both down while still root, before `USER x`.
COPY --link --from=stage_sb /opt/sb /opt/sb
COPY codespace/images/dev/rootfs/ /

COPY codespace/images/dev/script/setup-sysconf.sh /tmp/setup-sysconf.sh
COPY codespace/images/dev/script/setup-s6.sh /tmp/setup-s6.sh
RUN /tmp/setup-sysconf.sh \
  && mkdir -p /workspace \
  && chown 5230:5230 /workspace /opt \
  && /tmp/setup-s6.sh \
  && ln -s /opt/sb/store/zsh/bin/zsh /usr/bin \
  && ln -s /opt/sb/store/wget/bin/wget /usr/bin \
  && ln -s /opt/sb/store/less/bin/less /usr/bin \
  && ln -s /opt/sb/store/xz/bin/xz /usr/bin \
  && ln -s /opt/sb/store/openssh_gssapi/bin/ssh /usr/bin

USER x

# setup nixpkgs
ENV PATH=${PATH}:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin
RUN curl -L https://nixos.org/nix/install | sh -s -- --no-daemon \
  && nix-channel --add https://nixos.org/channels/nixpkgs-unstable nixpkgs \
  && nix-channel --update \
  && nix-env -iA nixpkgs.ollama-cpu nixpkgs.lemminx \
  && nix-collect-garbage -d \
  && nix-store --optimise

# setup rust
ENV CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup
ENV PATH=${PATH}:/opt/rust/cargo/bin
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y --profile default --no-modify-path --default-toolchain stable \
  && rustup component remove rust-docs

# setup java
RUN nix-env -iA nixpkgs.maven \
  && nix-env -iA nixpkgs.jdk8_headless -p /nix/var/nix/profiles/jdk8 \
  && nix-env -iA nixpkgs.jdk25_headless -p /nix/var/nix/profiles/jdk25 \
  && nix-collect-garbage -d \
  && nix-store --optimise

# setup nodejs
RUN nix-env -iA nixpkgs.nodejs_24 -p /nix/var/nix/profiles/nodejs-24 \
  && nix-env -iA nixpkgs.nodejs_24 \
  && nix-collect-garbage -d \
  && nix-store --optimise

# setup go
RUN nix-env -iA nixpkgs.go_1_26 -p /nix/var/nix/profiles/go-1_26 \
  && nix-env -iA nixpkgs.go_1_26 \
  && nix-collect-garbage -d \
  && nix-store --optimise

# setup python & tools
RUN uv python install --no-bin 3.9 3.10 3.11 3.12 3.13 3.14
RUN uv tool install licenseheaders \
  && uv tool install tensorboard --python 3.12 --with tensorboard-plugin-profile --with "setuptools==81.0.0"

# setup conda
COPY --chown=5230:5230 --from=stage_conda /opt/conda /opt/conda
ENV PATH=${PATH}:/opt/conda/condabin
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main \
  && conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# setup devspace
COPY --chown=5230:5230 ./ /opt/devspace
RUN bash /opt/devspace/dotfiles/setup.sh docker /opt/devspace/dotfiles \
  && ln -s /opt/devspace ~/devspace

# setup Trae user rules
RUN git clone --depth=1 https://github.com/curoky/agent-playbook /tmp/agent-playbook \
  && mkdir -p /home/x/.trae/user_rules \
  && rsync -a --delete /tmp/agent-playbook/.trae/rules/ /home/x/.trae/user_rules/ \
  && rm -rf /tmp/agent-playbook


USER root
RUN bash /opt/devspace/dotfiles/setup.sh docker /opt/devspace/dotfiles \
  && ln -s /opt/devspace ~/devspace

ENV PATH=${PATH}:/opt/sb/profile/s6/bin:/opt/sb/profile/s6/libexec
ENTRYPOINT ["/etc/s6/init/bin/init"]
