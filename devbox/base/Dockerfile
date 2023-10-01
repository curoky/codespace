# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=debian:12

FROM debian:latest AS stage_tools
RUN apt-get update -y && apt-get install -y curl zstd

COPY docker/base/script/install-pkgs.sh /tmp/install-pkgs.sh

RUN /tmp/install-pkgs.sh

FROM $BASE_IMAGE

ENV PATH=$PATH:/opt/conda/pipx/bin:/opt/tools/bin:/nix/var/nix/profiles/default/bin:/opt/conda/condabin \
  DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && apt-get install -y sudo locales

COPY docker/base/script/setup-user.sh /tmp/setup-user.sh
RUN /tmp/setup-user.sh

USER x

# copy multi stage build result
COPY --chown=5230:5230 --link --from=curoky/devspace:stage-conda /opt/conda /opt/conda
COPY --chown=5230:5230 --link --from=curoky/devspace:stage-nixpkg /nix /nix
COPY --chown=5230:5230 --link --from=curoky/devspace:stage-nixpkg /home/x/.local/state/nix /home/x/.local/state/nix
COPY --chown=5230:5230 --link --from=stage_tools /opt/tools /opt/tools

# setup tools
RUN sudo ln -s /opt/tools/store/zsh/bin/zsh /usr/bin \
  && sudo ln -s /opt/tools/store/wget/bin/wget /usr/bin \
  && sudo ln -s /opt/tools/store/curl/bin/curl /usr/bin \
  && sudo ln -s /opt/tools/store/openssh_gssapi/bin/ssh /usr/bin

# setup nixpkgs
RUN mkdir ~/.nix-defexpr \
  && ln -s ~/.local/state/nix/profiles/channels ~/.nix-defexpr/channels \
  && ln -s ~/.local/state/nix/profiles/profile ~/.nix-profile

# setup devspace
COPY --chown=5230:5230 ./ /home/x/app/devspace
RUN ln -sf /home/x/app/devspace ~/devspace \
  && bash ~/devspace/dotfiles/setup.sh docker ~/devspace/dotfiles

# other
RUN sudo mkdir -p /workspace \
  && sudo chown 5230:5230 /workspace /opt

USER root
RUN ln -sf /home/x/app ~/app \
  && ln -sf ~/app/devspace ~/devspace \
  && bash ~/devspace/docker/base/script/setup-sysconf.sh ~/devspace/dotfiles \
  && bash ~/devspace/dotfiles/setup.sh docker ~/devspace/dotfiles

ENTRYPOINT ["/home/x/app/devspace/docker/base/script/entrypoint.sh"]
