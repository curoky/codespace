FROM docker.io/lobehub/lobehub:2.2.17 AS lobehub
FROM docker.io/library/node:24.21.0-bookworm-slim AS node
FROM docker.io/paradedb/paradedb:0.25.9-pg17

# LobeHub's official runtime is a scratch image. Reuse its prebuilt application
# while keeping ParadeDB's PostgreSQL 17, pg_search, and pgvector installation.
RUN apt-get update -y \
  && apt-get install -y --no-install-recommends proxychains4 \
  && rm -rf /var/lib/apt/lists/* \
  && groupadd --gid 1001 nodejs \
  && useradd --system --uid 1001 --gid nodejs --home-dir /app --shell /usr/sbin/nologin nextjs \
  && ln -sf /usr/bin/proxychains4 /bin/proxychains

COPY --from=node /usr/local/bin/node /bin/node
COPY --from=lobehub --chown=nextjs:nodejs /app /app

COPY platform/container/services/lobehub/binman.yaml /tmp/binman.yaml
RUN curl -fsSL https://raw.githubusercontent.com/curoky/standalone-binaries/refs/heads/master/cmd/binman/install.sh \
    | bash -s -- --prefix /opt/bm/bin \
  && /opt/bm/bin/bm sync /tmp/binman.yaml

ENV PATH="/opt/bm/bin:/opt/bm/profile/s6/bin:/opt/bm/profile/s6/libexec:/usr/lib/postgresql/17/bin:$PATH" \
    NODE_ENV=production \
    NODE_OPTIONS="--dns-result-order=ipv4first --use-openssl-ca" \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    MIDDLEWARE_REWRITE_THROUGH_LOCAL=1 \
    DATABASE_DRIVER=node \
    PGDATA=/var/lib/codespace/lobehub/postgresql \
    LOBEHUB_HOST=0.0.0.0 \
    LOBEHUB_INTERNAL_PORT=3211 \
    APP_URL=http://localhost:3210 \
    AUTH_COOKIE_PREFIX=codespace-lobehub \
    ENABLED_OPENAI=1 \
    OPENAI_API_KEY=local \
    OPENAI_PROXY_URL=http://10.89.0.1:8003/v1 \
    OPENAI_MODEL_LIST="-all,+Qwen/Qwen3.8-Flash-Next-FP8=Qwen3.8 Flash Next FP8"

COPY platform/container/workspace/rootfs/etc/s6/skel/ /etc/s6/skel/
COPY platform/container/services/lobehub/rootfs/ /
RUN chmod +x /opt/codespace/lobehub/*.sh
COPY platform/container/workspace/scripts/install-s6.sh /tmp/install-s6.sh
RUN /tmp/install-s6.sh

EXPOSE 3210/tcp

ENTRYPOINT ["/etc/s6/init/bin/init"]
