FROM debian:buster-backports AS builder

RUN cat /etc/apt/sources.list \
  && sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list \
  && sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list.d/backports.list \
  && sed -i 's/security.debian.org/archive.debian.org/g' /etc/apt/sources.list \
  && sed -i '/stretch-updates/d' /etc/apt/sources.list \
  && apt-get update -y

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends \
    # for install gcc
    curl tar ca-certificates dpkg-dev flex gcc g++ file tzdata unzip \
    # for install python
    tk-dev uuid-dev libgdbm-dev libgdbm-compat-dev libssl-dev libbz2-dev liblzma-dev zlib1g-dev \
    libreadline-dev libncurses5-dev libncursesw5-dev libsqlite3-dev libffi-dev

ARG PYTHON_VERSION 3.13.7

RUN mkdir -p /tmp/python/src \
  && curl -L "https://www.python.org/ftp/python/${PYTHON_VERSION%%[a-z]*}/Python-$PYTHON_VERSION.tar.xz" \
    | tar -x --xz -C /tmp/python/src --strip-components 1

RUN cd /tmp/python/src \
  && ./configure \
    --prefix=/opt/python/python-$PYTHON_VERSION \
		--build="x86_64-linux-gnu" \
		--enable-loadable-sqlite-extensions \
		--enable-optimizations \
		--enable-option-checking=fatal \
		--enable-shared \
		--with-lto \
		--with-ensurepip \
  && make -j "$(nproc)" \
  && make install


FROM debian:stable-slim

COPY --from=builder /opt/python /opt/python
