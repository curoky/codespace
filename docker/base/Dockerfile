# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=debian:12

FROM $BASE_IMAGE

ENV PATH=$PATH:/home/x/app/pipx/bin:/home/x/app/prebuilt/bin:/nix/var/nix/profiles/default/bin \
  DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && apt-get install -y sudo curl

COPY docker/base/script/setup-user.sh /tmp/setup-user.sh
RUN /tmp/setup-user.sh

USER x

# copy multi stage build result
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-conda /home/x/app/conda /home/x/app/conda
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-conda /home/x/app/pipx /home/x/app/pipx
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-nixpkg /nix /nix
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-nixpkg /home/x/.local/state/nix /home/x/.local/state/nix

# setup prebuilt-sre-tools
RUN curl -sSL -o /tmp/prebuilt-sre-tools.linux-x86_64.gzip.sh https://github.com/curoky/dotbox/releases/download/v1.0/prebuilt-sre-tools.linux-x86_64.gzip.sh \
  && bash /tmp/prebuilt-sre-tools.linux-x86_64.gzip.sh \
  && rm -rf /tmp/prebuilt-sre-tools.linux-x86_64.gzip.sh \
  && sudo ln -s /home/x/app/prebuilt/pkgs/zsh/bin/zsh /usr/bin \
  && sudo ln -s /home/x/app/prebuilt/pkgs/wget/bin/wget /usr/bin

# setup nixpkgs
RUN ln -s ~/.local/state/nix/profiles/profile ~/.nix-profile \
  && mkdir ~/.nix-defexpr \
  && ln -s ~/.local/state/nix/profiles/channels ~/.nix-defexpr/channels

# setup dotbox
COPY --chown=5230:5230 ./ /home/x/app/dotbox
RUN ln -sf /home/x/app/dotbox ~/dotbox \
  && ~/dotbox/config/setup.sh docker ~/dotbox/config

# other
RUN sudo mkdir -p /workspace \
  && sudo chown x:x /workspace /opt

# TODO: remove
RUN sudo mkdir -p /app/prebuilt \
  && sudo chown -R x:x /app \
  && ln -s /home/x/app/prebuilt ~/prebuilt \
  && ln -s /home/x/app/prebuilt /app/prebuilt

USER root
RUN ln -sf /home/x/app/dotbox ~/dotbox \
  && ~/dotbox/docker/base/script/setup-sysconf.sh ~/dotbox/config \
  && ~/dotbox/config/setup.sh docker ~/dotbox/config

ENTRYPOINT ["/home/x/app/dotbox/docker/base/script/entrypoint.sh"]
