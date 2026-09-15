#!/usr/bin/env bash

set -euo pipefail

data_root="${LOBEHUB_DATA_DIR:-/var/lib/codespace/lobehub}"
config_dir="${data_root}/config"
port=3210

install -d -m 0700 "${config_dir}"
umask 077

if [[ ! -s "${config_dir}/key-vaults-secret" ]]; then
  openssl rand -base64 32 >"${config_dir}/key-vaults-secret.tmp"
  mv "${config_dir}/key-vaults-secret.tmp" "${config_dir}/key-vaults-secret"
fi

if [[ ! -s "${config_dir}/auth-secret" ]]; then
  openssl rand -base64 32 >"${config_dir}/auth-secret.tmp"
  mv "${config_dir}/auth-secret.tmp" "${config_dir}/auth-secret"
fi

if [[ ! -s "${config_dir}/jwks-key" ]]; then
  /bin/node /opt/codespace/lobehub/create-jwks.js >"${config_dir}/jwks-key.tmp"
  mv "${config_dir}/jwks-key.tmp" "${config_dir}/jwks-key"
fi

if [[ "$(psql --username=postgres --dbname=postgres --tuples-only --no-align \
  --command="SELECT 1 FROM pg_database WHERE datname = 'lobehub'")" != "1" ]]; then
  createdb --username=postgres --owner=postgres lobehub
fi

export APP_URL="${APP_URL:-http://localhost:${port}}"
export AUTH_SECRET
AUTH_SECRET=$(<"${config_dir}/auth-secret")
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres@127.0.0.1:5432/lobehub}"
export HOSTNAME="${LOBEHUB_HOST:-0.0.0.0}"
export INTERNAL_APP_URL="http://127.0.0.1:${port}"
export JWKS_KEY
JWKS_KEY=$(<"${config_dir}/jwks-key")
export KEY_VAULTS_SECRET
KEY_VAULTS_SECRET=$(<"${config_dir}/key-vaults-secret")
export PORT="${port}"

cd /app
exec s6-setuidgid nextjs /bin/node /app/startServer.js
