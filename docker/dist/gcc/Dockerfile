# syntax=docker/dockerfile:1.9.0
FROM curoky/dotbox:stage-nixpkg AS stage-nixpkg
RUN nix-env -p /nix/var/nix/profiles/gcc -iA \
    nixpkgs.mold nixpkgs.lld_16 \
    nixpkgs.jemalloc nixpkgs.flamegraph \
  && nix-collect-garbage

FROM curoky/dotbox:base-ubuntu24.04

COPY --chown=5230:5230 --link --from=stage-nixpkg /nix /nix
COPY --chown=5230:5230 --link --from=stage-nixpkg /home/x/.local/state/nix /home/x/.local/state/nix
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-conda /app/conda /app/conda
COPY --chown=5230:5230 --link --from=curoky/dotbox:stage-conda /app/pipx /app/pipx

USER root
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    gcc-13 g++-13 \
  && /app/dotbox/docker/dist/gcc/script/setup-sys-change-default-gcc.sh 13

USER root
ENTRYPOINT ["/app/dotbox/docker/base/script/entrypoint.sh"]
