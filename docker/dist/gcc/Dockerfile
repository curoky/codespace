# syntax=docker/dockerfile:1.9.0
FROM curoky/dotbox:stage-nixpkg AS stage-nixpkg
RUN nix-env -p /nix/var/nix/profiles/gcc -iA \
    nixpkgs.mold nixpkgs.lld_16 \
    nixpkgs.jemalloc nixpkgs.flamegraph \
  && nix-collect-garbage

FROM curoky/dotbox:base-ubuntu24.04

COPY --chown=x:x --link --from=stage-nixpkg /nix /nix
COPY --chown=x:x --link --from=stage-nixpkg /home/x/.local/state/nix /home/x/.local/state/nix
COPY --chown=x:x --link --from=curoky/dotbox:stage-conda /app/conda /app/conda
COPY --chown=x:x --link --from=curoky/dotbox:stage-conda /app/pipx /app/pipx

USER root
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    gcc-13 g++-13

USER root
ENTRYPOINT ["/app/dotbox/docker/base/script/entrypoint.sh"]
