# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=debian:12

################################ stage/static tools ################################
FROM debian:latest AS stage_tools
RUN apt-get update -y && apt-get install -y curl zstd

COPY dist/image/base/script/install-pkgs.sh /tmp/install-pkgs.sh

RUN /tmp/install-pkgs.sh

# ################################ stage/conda environ ################################
FROM debian:stable-slim as stage_conda

RUN apt-get update -y \
  && apt-get install -y curl gcc g++ git pkg-config \
  && curl -sSL -o /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
  && bash /tmp/miniconda.sh -b -u -p /opt/conda

COPY dist/image/stage/conda/setup-conda-env.sh /opt/conda/condabin/setup-conda-env.sh

# ################################ stage/python environ ################################
# FROM debian:latest AS stage_python
# ENV PATH=${PATH}:/root/.local/bin

# RUN apt-get update -y \
#   && apt-get -y install curl gcc g++ \
#     # just for monopoly
#     libpoppler-cpp-dev

# RUN curl -L https://astral.sh/uv/install.sh | sh \
#   && id && ls -la /root/.local/bin

# COPY deps/uv-pipx /tmp/uv-pipx
# RUN /tmp/uv-pipx/install.sh

# COPY deps/uv-conda /tmp/uv-conda
# RUN /tmp/uv-conda/install.sh py3

################################ stage/nixpkgs ################################
# FROM debian:latest AS stage_nixpkgs
# RUN apt-get update -y \
#   && apt-get install -y curl xz-utils sudo \
#   && groupadd -g 5230 -o x \
#   && useradd -m -u 5230 -g 5230 x \
#   && mkdir -m 0755 /nix \
#   && chown x:x /nix

# USER x

# ENV PATH=$PATH:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin \
#   NIXPKGS_ALLOW_UNFREE=1 \
#   NIXPKGS_ALLOW_BROKEN=1

# RUN curl -L https://nixos.org/nix/install | sh -s -- --no-daemon \
#   && nix-channel --add https://nixos.org/channels/nixpkgs-unstable nixpkgs \
#   && nix-channel --update

################################ main ################################
FROM $BASE_IMAGE

ENV PATH=${PATH}:/opt/tools/bin \
  DEBIAN_FRONTEND=noninteractive

ARG BASE_IMAGE
COPY dist/image/base/script/patch-apt.sh /tmp/patch-apt.sh
RUN /tmp/patch-apt.sh ${BASE_IMAGE} \
  && apt-get update -y && apt-get install -y sudo locales

COPY dist/image/base/script/setup-user.sh /tmp/setup-user.sh
RUN /tmp/setup-user.sh

USER x

# setup tools
COPY --chown=5230:5230 --link --from=stage_tools /opt/tools /opt/tools
RUN sudo ln -s /opt/tools/store/zsh-bundle/bin/zsh /usr/bin \
  && sudo ln -s /opt/tools/store/wget/bin/wget /usr/bin \
  && sudo ln -s /opt/tools/store/curl/bin/curl /usr/bin \
  && sudo ln -s /opt/tools/store/openssh_gssapi/bin/ssh /usr/bin

# setup nixpkgs
ENV PATH=${PATH}:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin
RUN curl -L https://nixos.org/nix/install | sh -s -- --no-daemon \
  && nix-channel --add https://nixos.org/channels/nixpkgs-unstable nixpkgs \
  && nix-channel --update

# setup uv
COPY dist/image/stage/uv/pipx /tmp/uv-pipx
RUN /tmp/uv-pipx/install.sh
COPY dist/image/stage/uv/conda /tmp/uv-conda
RUN /tmp/uv-conda/install.sh py3

# setup conda
COPY --chown=5230:5230 --from=stage_conda /opt/conda /opt/conda
ENV PATH=${PATH}:/opt/conda/condabin
RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main \
  && conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r

# setup devspace
COPY --chown=5230:5230 ./ /opt/devspace
RUN bash /opt/devspace/dotfiles/setup.sh docker /opt/devspace/dotfiles \
  && ln -s /opt/devspace ~/devspace

# other
RUN sudo mkdir -p /workspace \
  && sudo chown 5230:5230 /workspace /opt

USER root
RUN bash /opt/devspace/dist/image/base/script/setup-sysconf.sh /opt/devspace/dotfiles \
  && bash /opt/devspace/dotfiles/setup.sh docker /opt/devspace/dotfiles \
  && ln -s /opt/devspace ~/devspace

ENTRYPOINT ["/opt/devspace/dist/image/base/script/entrypoint.sh"]
