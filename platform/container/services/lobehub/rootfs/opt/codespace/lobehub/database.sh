#!/usr/bin/env bash

set -euo pipefail

pgdata="${PGDATA:-/var/lib/codespace/lobehub/postgresql}"

install -d -m 0700 -o postgres -g postgres "${pgdata}"
install -d -m 2775 -o postgres -g postgres /run/postgresql

if [[ ! -s "${pgdata}/PG_VERSION" ]]; then
  if [[ -n "$(find "${pgdata}" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "database directory is non-empty but has no PG_VERSION: ${pgdata}" >&2
    exit 1
  fi

  s6-setuidgid postgres initdb \
    --pgdata="${pgdata}" \
    --auth-local=trust \
    --auth-host=trust \
    --data-checksums \
    --encoding=UTF8 \
    --locale=C.UTF-8 \
    --no-instructions
fi

exec s6-setuidgid postgres postgres \
  --data-directory="${pgdata}" \
  -c listen_addresses=127.0.0.1 \
  -c shared_preload_libraries=pg_search \
  -c unix_socket_directories=/run/postgresql
