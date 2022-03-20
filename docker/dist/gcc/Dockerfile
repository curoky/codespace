FROM curoky/dotbox:minimal-ubuntu24.04

USER root
## Setup gcc
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    gcc-13 g++-13

USER x

## Setup tools from nixpkgs
RUN nix-env -p /nix/var/nix/profiles/gcc -iA \
    nixpkgs.ninja nixpkgs.distcc nixpkgs.ccache nixpkgs.scons nixpkgs.meson \
    nixpkgs.mold nixpkgs.lld_16 \
    nixpkgs.jemalloc nixpkgs.flamegraph
