# --------------------------------- Builder ----------------------------------
FROM docker.io/library/node:22.23.2-bookworm-slim AS build

ARG CHATBOX_VERSION=v1.23.2

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl patch \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /src
RUN curl -fsSL "https://github.com/chatboxai/chatbox/archive/refs/tags/${CHATBOX_VERSION}.tar.gz" \
    | tar -xz --strip-components=1 \
  && corepack enable \
  && corepack prepare pnpm@10.33.0 --activate

COPY platform/container/services/chatbox/defaults.patch /tmp/defaults.patch
RUN patch --fuzz=0 -p1 </tmp/defaults.patch \
  && pnpm install --frozen-lockfile \
  && CHATBOX_BUILD_PLATFORM=web CHATBOX_ELECTRON_VITE_TARGET=renderer \
    pnpm exec electron-vite build \
  && find release/app/dist/renderer -type f -name '*.map' -delete

# --------------------------------- Runtime ----------------------------------
FROM ghcr.io/curoky/codespace:service-s6

ENV CHATBOX_API_UPSTREAM=http://codespace-service-sglang:8080

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends gettext-base nginx \
  && rm -rf /var/lib/apt/lists/* \
  && rm /etc/nginx/sites-enabled/default

COPY --from=build /src/release/app/dist/renderer/ /usr/share/nginx/html/
COPY platform/container/services/chatbox/default.conf.template /etc/nginx/templates/default.conf.template
COPY platform/container/services/chatbox/rootfs/ /
RUN /etc/s6/install-s6.sh
