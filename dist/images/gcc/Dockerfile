# syntax=docker/dockerfile:1.9.0
FROM curoky/devspace:base-debian10

USER x
# RUN apt-get update -y \
#   && apt-get install -y --no-install-recommends \
#     gcc-13 g++-13 \
#   && /home/x/app/devspace/docker/dist/gcc/script/setup-sys-change-default-gcc.sh 13

COPY --chown=5230:5230 --from=curoky/devspace:stage-gcc-14.2.0 /opt/gcc/gcc-14.2.0 /opt/gcc/gcc-14.2.0
COPY --chown=5230:5230 --from=curoky/devspace:stage-gcc-14.2.0 /opt/binutils /opt/binutils

COPY script/setup-custom-installed-gcc.sh /tmp/setup-custom-installed-gcc.sh

RUN sudo apt-get install -y libc6-dev \
  && sudo /tmp/setup-custom-installed-gcc.sh \
  && sudo ln -s /opt/conda/envs/py3/bin/python3 /usr/bin/python3

USER root
ENTRYPOINT ["/home/x/app/devspace/dist/images/base/script/entrypoint.sh"]
