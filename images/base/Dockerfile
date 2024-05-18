# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=debian:12

################################ stage/static tools ################################
FROM debian:latest AS stage_tools
RUN apt-get update -y && apt-get install -y curl zstd

COPY images/base/script/install-pkgs.sh /tmp/install-pkgs.sh
RUN /tmp/install-pkgs.sh

# ################################ stage/conda environ ################################
FROM debian:stable-slim AS stage_conda

RUN apt-get update -y \
  && apt-get install -y curl gcc g++ git pkg-config \
  && curl -sSL -o /tmp/miniconda.sh https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
  && bash /tmp/miniconda.sh -b -u -p /opt/conda

COPY images/base/stage/conda/setup-conda-env.sh /opt/conda/condabin/setup-conda-env.sh

################################ main ################################
FROM $BASE_IMAGE

ENV PATH=${PATH}:/opt/tools/bin \
  DEBIAN_FRONTEND=noninteractive

ARG BASE_IMAGE
COPY images/base/script/patch-apt.sh /tmp/patch-apt.sh
RUN /tmp/patch-apt.sh ${BASE_IMAGE} \
  && apt-get update -y && apt-get install -y sudo locales

COPY images/base/script/setup-user.sh /tmp/setup-user.sh
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
ENV PATH=${PATH}:/opt/pipx/bin
COPY images/base/stage/uv/pipx /tmp/uv-pipx
RUN /tmp/uv-pipx/install.sh && pipx install licenseheaders conan
COPY images/base/stage/uv/conda /tmp/uv-conda
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
RUN bash /opt/devspace/images/base/script/setup-sysconf.sh /opt/devspace/dotfiles \
  && bash /opt/devspace/dotfiles/setup.sh docker /opt/devspace/dotfiles \
  && ln -s /opt/devspace ~/devspace

ENTRYPOINT ["/opt/devspace/images/base/script/entrypoint.sh"]
