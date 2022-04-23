FROM docker.io/curoky/dotbox:stage-nixpkg as stage-nixpkg
RUN nix-env -p /nix/var/nix/profiles/gcc -iA \
    nixpkgs.mold nixpkgs.lld_16 \
    nixpkgs.jemalloc nixpkgs.flamegraph \
  && nix-collect-garbage

FROM docker.io/curoky/dotbox:base-ubuntu24.04

COPY --chown=1000:1000 --link --from=stage-nixpkg /nix /nix
COPY --chown=1000:1000 --link --from=stage-nixpkg /home/x/.local/state/nix /home/x/.local/state/nix
COPY --chown=1000:1000 --link --from=stage-nixpkg /home/x/.local/state/nix /root/.local/state/nix
COPY --chown=1000:1000 --link --from=docker.io/curoky/dotbox:stage-conda /app/conda /app/conda
COPY --chown=1000:1000 --link --from=docker.io/curoky/dotbox:stage-conda /app/pipx /app/pipx

USER root
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    gcc-13 g++-13

USER root
ENTRYPOINT ["/app/dotbox/docker/dist/default/script/entrypoint.sh"]
