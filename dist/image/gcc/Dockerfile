# syntax=docker/dockerfile:1.9.0
FROM curoky/devspace:base-debian10

RUN cat /etc/apt/sources.list \
  && sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list \
  # && sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list.d/backports.list \
  && sed -i 's/security.debian.org/archive.debian.org/g' /etc/apt/sources.list \
  # && sed -i '/stretch-updates/d' /etc/apt/sources.list \
  && apt-get update -y

USER x

# RUN apt-get update -y \
#   && apt-get install -y --no-install-recommends \
#     gcc-13 g++-13 \
#   && /home/x/app/devspace/dist/image/gcc/script/setup-sys-change-default-gcc.sh 13

COPY --chown=5230:5230 --from=curoky/devspace:deps-gcc-13.4.0 /opt/gcc/gcc-13.4.0 /opt/gcc/gcc-13.4.0
COPY --chown=5230:5230 --from=curoky/devspace:deps-gcc-14.3.0 /opt/gcc/gcc-14.3.0 /opt/gcc/gcc-14.3.0
COPY --chown=5230:5230 --from=curoky/devspace:deps-gcc-15.1.0 /opt/gcc/gcc-15.1.0 /opt/gcc/gcc-15.1.0
COPY --chown=5230:5230 --from=curoky/devspace:deps-gcc-15.1.0 /opt/binutils /opt/binutils

COPY script/setup-custom-installed-gcc.sh /tmp/setup-custom-installed-gcc.sh

RUN sudo apt-get install -y libc6-dev \
  && sudo /tmp/setup-custom-installed-gcc.sh "15.1.0" \
  && sudo ln -s /opt/conda/envs/py3/bin/python3 /usr/bin/python3

USER root
ENTRYPOINT ["/home/x/app/devspace/dist/image/base/script/entrypoint.sh"]
