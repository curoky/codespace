ARG BASE_IMAGE=ubuntu:24.04

FROM $BASE_IMAGE

ENV PATH=$PATH:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin:/app/pipx/bin:/app/dotbox/docker/stage/conda \
  DEBIAN_FRONTEND=noninteractive

COPY --chown=1000:1000 ./ /app/dotbox
RUN ln -sf /app/dotbox ~/dotbox \
  && /app/dotbox/docker/base/script/setup-sysconf.sh ~/dotbox/config \
  && /app/dotbox/docker/base/script/setup-userconf.sh ~/dotbox/config \
  && mkdir -p /workspace \
  && chown x:x /workspace /app

USER x
RUN ln -sf /app/dotbox ~/dotbox \
  && /app/dotbox/docker/base/script/setup-userconf.sh ~/dotbox/config
