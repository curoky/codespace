# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=debian:12

FROM $BASE_IMAGE

ENV PATH=$PATH:/home/x/app/pipx/bin:/home/x/app/prebuilt/bin:/nix/var/nix/profiles/default/bin \
  DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && apt-get install -y sudo curl zstd

COPY docker/base/script/setup-user.sh /tmp/setup-user.sh
RUN /tmp/setup-user.sh

USER x

# copy multi stage build result
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-conda /home/x/app/conda /home/x/app/conda
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-nixpkg /nix /nix
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-nixpkg /home/x/.local/state/nix /home/x/.local/state/nix

# setup packed-sre-tools
RUN curl -sSL -o /tmp/packed-sre-tools.linux-x86_64.sh https://github.com/curoky/dotbox/releases/download/v1.0/packed-sre-tools.linux-x86_64.zstd.sh \
  && bash /tmp/packed-sre-tools.linux-x86_64.sh \
  && rm -rf /tmp/packed-sre-tools.linux-x86_64.sh \
  && sudo ln -s /home/x/app/prebuilt/pkgs/zsh/bin/zsh /usr/bin \
  && sudo ln -s /home/x/app/prebuilt/pkgs/wget/bin/wget /usr/bin

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
