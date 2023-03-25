# syntax=docker/dockerfile:1.9.0
ARG BASE_IMAGE=debian:12

FROM $BASE_IMAGE

ENV PATH=$PATH:/app/pipx/bin:/app/prebuilt/bin:/nix/var/nix/profiles/default/bin \
  DEBIAN_FRONTEND=noninteractive

RUN apt-get update -y && apt-get install -y sudo curl

RUN curl -SL https://github.com/curoky/dotbox/releases/download/v1.0/prebuilt-sre-tools.linux-x86_64.tar.gz -o prebuilt.tar.gz \
  && mkdir -p /app/prebuilt \
  && tar -xzf prebuilt.tar.gz -C /app/prebuilt --strip-components=1 \
  && chown -R 5230:5230 /app/prebuilt \
  && rm -rf prebuilt.tar.gz

COPY --chown=5230:5230 ./ /app/dotbox

RUN ln -sf /app/dotbox ~/dotbox \
  && ln -s /app/prebuilt ~/prebuilt \
  && ln -s /app/prebuilt/pkgs/zsh/bin/zsh /usr/bin \
  && ln -s /app/prebuilt/pkgs/wget/bin/wget /usr/bin \
  && /app/dotbox/docker/base/script/setup-sysconf.sh ~/dotbox/config \
  && /app/dotbox/config/setup.sh docker ~/dotbox/config \
  && mkdir -p /workspace \
  && chown x:x /workspace /app /opt

COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-conda /app/conda /app/conda
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-conda /app/pipx /app/pipx
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-nixpkg /nix /nix
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-nixpkg /home/x/.local/state/nix /home/x/.local/state/nix

USER x
RUN ln -s /app/dotbox ~/dotbox \
  && ln -s /app/prebuilt ~/prebuilt \
  && ln -s ~/.local/state/nix/profiles/profile ~/.nix-profile \
  && mkdir ~/.nix-defexpr \
  && ln -s ~/.local/state/nix/profiles/channels ~/.nix-defexpr/channels \
  && /app/dotbox/config/setup.sh docker ~/dotbox/config

USER root
ENTRYPOINT ["/app/dotbox/docker/base/script/entrypoint.sh"]
