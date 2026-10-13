FROM ghcr.io/curoky/codespace:service-s6
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

RUN /usr/local/bin/bm --prefix /usr/local install uv
COPY platform/container/services/asr/scheduler/ /opt/asr/scheduler/
COPY platform/container/services/asr/protocol.py /opt/asr/protocol.py
COPY platform/container/services/asr/scheduler/rootfs/ /
RUN rm -f /etc/s6/s6-rc.d/default/contents.d/miniserve-logs \
    /etc/s6/s6-rc.d/default/contents.d/supercronic \
  && mkdir -p /data/asr \
  && chown x:x /data/asr /opt/asr/scheduler
USER x
RUN uv python install 3.14.7 \
  && uv sync --locked --no-dev --project /opt/asr/scheduler \
  && rm -rf /home/x/.cache/uv
USER root
RUN /etc/s6/install-s6.sh
EXPOSE 8080
