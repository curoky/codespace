# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=ubuntu:24.04

FROM $BASE_IMAGE

ENV PATH=$PATH:/app/pipx/bin:/app/prebuilt/bin:/app/prebuilt/extra/bin:/nix/var/nix/profiles/default/bin \
  DEBIAN_FRONTEND=noninteractive

COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-prebuilt /output /app/prebuilt
COPY --chown=5230:5230 ./ /app/dotbox

RUN apt-get update -y && apt-get install -y sudo

RUN ln -sf /app/dotbox ~/dotbox \
  && ln -s /app/prebuilt ~/prebuilt \
  && ln -s /app/prebuilt/bin/zsh /usr/bin \
  && /app/dotbox/docker/base/script/setup-sysconf.sh ~/dotbox/config \
  && /app/dotbox/docker/base/script/setup-userconf.sh ~/dotbox/config \
  && mkdir -p /workspace \
  && chown x:x /workspace /app

USER x
RUN ln -s /app/dotbox ~/dotbox \
  && ln -s /app/prebuilt ~/prebuilt \
  && ln -s ~/.local/state/nix/profiles/profile ~/.nix-profile \
  && mkdir ~/.nix-defexpr \
  && ln -s ~/.local/state/nix/profiles/channels ~/.nix-defexpr/channels \
  && /app/dotbox/docker/base/script/setup-userconf.sh ~/dotbox/config
