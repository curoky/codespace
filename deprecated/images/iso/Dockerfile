FROM debian:13

RUN apt-get update && apt-get install -y \
    live-build \
    qemu-user-static \
    binfmt-support \
    xorriso debootstrap \
    ncdu \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /build
