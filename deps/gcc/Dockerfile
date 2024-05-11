# https://github.com/docker-library/gcc/blob/master/14/Dockerfile
# https://gcc.gnu.org/install/build.html

FROM debian:buster-backports AS builder

RUN cat /etc/apt/sources.list \
  && sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list \
  && sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list.d/backports.list \
  && sed -i 's/security.debian.org/archive.debian.org/g' /etc/apt/sources.list \
  && sed -i '/stretch-updates/d' /etc/apt/sources.list \
  && apt-get update -y

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    # basic tools
    curl tar ca-certificates dpkg-dev file tzdata \
    # compiler tools
    gcc g++ \
    # for install binutils
    make texinfo \
    # for install gcc
    bison flex gawk libgmp-dev libmpfr-dev libmpc-dev libisl-dev \
    zlib1g-dev libzstd-dev libexpat1-dev

# install latest binutils
RUN mkdir -p /tmp/binutils/src \
  && curl -sSL https://ftpmirror.gnu.org/gnu/binutils/binutils-2.42.tar.gz | tar -x --gunzip -C /tmp/binutils/src --strip-components 1 \
  && mkdir -p /tmp/binutils/build && cd /tmp/binutils/build \
  && /tmp/binutils/src/configure --prefix=/opt/binutils --disable-multilib \
  && make -j "$(nproc)" && make install \
  && find /opt/binutils/bin/ -type f -exec ln -sf {} /usr/bin \; \
  # && /tmp/binutils/src/configure --prefix=/usr --disable-multilib \
  # && make -j$(nproc) && make install \
  && rm -rf /tmp/binutils

ARG GCC_VERSION=15.1.0

RUN mkdir -p /tmp/gcc/src \
  && curl -L https://ftpmirror.gnu.org/gcc/gcc-${GCC_VERSION}/gcc-${GCC_VERSION}.tar.xz | tar -x --xz -C /tmp/gcc/src --strip-components 1 \
  && cd /tmp/gcc/src \
  && ./contrib/download_prerequisites \
  && mkdir -p /tmp/gcc/build && cd /tmp/gcc/build \
  && /tmp/gcc/src/configure \
    # CXXFLAGS="-fPIC" CFLAGS="-fPIC" \
    --prefix=/opt/gcc/gcc-${GCC_VERSION} \
    # --with-sysroot=/opt/gcc/gcc-14.2.0 \
    --build="x86_64-linux-gnu" \
    --disable-multilib \
    --disable-nls \
    --enable-languages=c,c++ \
    --enable-checking=release \
    --enable-lto \
    --with-system-zlib \
    --with-zstd \
    --with-isl \
    ''

ARG ENABLE_2STAGE=false
RUN [ ${ENABLE_2STAGE} = "true" ] && cd /tmp/gcc/build && make -j"$(nproc)" profiledbootstrap && make install-strip || echo "Skipping"
RUN [ ${ENABLE_2STAGE} = "false" ] && cd /tmp/gcc/build && make -j"$(nproc)" && make install-strip || echo "Skipping"

# gcc installs .so files in /usr/local/lib64 (and /usr/local/lib)...
# RUN set -ex; \
# # this filename needs to sort higher than all the architecture filenames ("aarch64-...", "armeabi...", etc)
#   { echo '/usr/local/lib64'; echo '/usr/local/lib'; } > /etc/ld.so.conf.d/000-local-lib.conf; \
#   ldconfig -v; \
#   # the libc created by gcc might be too old for a newer Debian
#   # check that the Debian libstdc++ doesn't have newer requirements than the gcc one
#   deb="$(readlink -ve /usr/lib/*/libstdc++.so* | head -1)"; \
#   gcc="$(readlink -ve /usr/local/lib*/libstdc++.so | head -1)"; \
# # using LD_PRELOAD to make sure "abidiff" itself doesn't fail with the exact error we're trying to test for 😂😭
#   LD_PRELOAD="$deb" abidiff --no-added-syms "$deb" "$gcc"

FROM debian:stable-slim

COPY --from=builder /opt/binutils /opt/binutils
COPY --from=builder /opt/gcc /opt/gcc
