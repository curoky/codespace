# syntax=docker/dockerfile:1.9.0
FROM curoky/dotbox:base-ubuntu24.10

USER root
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    gcc-13 g++-13 \
  && /home/x/app/dotbox/docker/dist/gcc/script/setup-sys-change-default-gcc.sh 13

USER x
ENV PATH=$PATH:/nix/var/nix/profiles/default/bin:/home/x/.nix-profile/bin: \
  NIXPKGS_ALLOW_UNFREE=1 \
  NIXPKGS_ALLOW_BROKEN=1

RUN nix-env -p /nix/var/nix/profiles/gcc -iA \
    nixpkgs.mold nixpkgs.jemalloc nixpkgs.flamegraph \
  && nix-collect-garbage

USER root
ENTRYPOINT ["/home/x/app/dotbox/docker/base/script/entrypoint.sh"]
