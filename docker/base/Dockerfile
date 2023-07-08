# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=debian:12

FROM debian:latest AS stage_tools
RUN apt-get update -y && apt-get install -y curl zstd

COPY docker/base/script/install-pkgs.sh /tmp/install-pkgs.sh

RUN /tmp/install-pkgs.sh

FROM $BASE_IMAGE

ENV PATH=$PATH:/home/x/app/pipx/bin:/home/x/app/tools/bin:/nix/var/nix/profiles/default/bin:/home/x/app/conda/condabin \
  DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && apt-get install -y sudo locales

COPY docker/base/script/setup-user.sh /tmp/setup-user.sh
RUN /tmp/setup-user.sh

USER x

# copy multi stage build result
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-conda /home/x/app/conda /home/x/app/conda
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-nixpkg /nix /nix
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-nixpkg /home/x/.local/state/nix /home/x/.local/state/nix
COPY --chown=5230:5230 --link --from=stage_tools /home/x/app/tools /home/x/app/tools

# setup tools
RUN sudo ln -s /home/x/app/tools/store/zsh/bin/zsh /usr/bin \
  && sudo ln -s /home/x/app/tools/store/wget/bin/wget /usr/bin \
  && sudo ln -s /home/x/app/tools/store/curl/bin/curl /usr/bin \
  && sudo ln -s /home/x/app/tools/store/openssh_gssapi/bin/ssh /usr/bin

# setup nixpkgs
RUN mkdir ~/.nix-defexpr \
  && ln -s ~/.local/state/nix/profiles/channels ~/.nix-defexpr/channels \
  && ln -s ~/.local/state/nix/profiles/profile ~/.nix-profile

# setup dotbox
COPY --chown=5230:5230 ./ /home/x/app/dotbox
RUN ln -sf /home/x/app/dotbox ~/dotbox \
  && bash ~/dotbox/config/setup.sh docker ~/dotbox/config

# other
RUN sudo mkdir -p /workspace \
  && sudo chown 5230:5230 /workspace /opt

USER root
RUN ln -sf /home/x/app ~/app \
  && ln -sf ~/app/dotbox ~/dotbox \
  && bash ~/dotbox/docker/base/script/setup-sysconf.sh ~/dotbox/config \
  && bash ~/dotbox/config/setup.sh docker ~/dotbox/config

ENTRYPOINT ["/home/x/app/dotbox/docker/base/script/entrypoint.sh"]
