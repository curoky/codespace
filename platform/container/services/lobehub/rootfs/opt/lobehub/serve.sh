#!/usr/bin/env bash

set -euo pipefail

readonly config_dir=/var/lib/codespace/lobehub/config
readonly auto_auth_email=codespace@codespace.invalid

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

if [[ ! -s "${config_dir}/auto-auth-password" ]]; then
  openssl rand -base64 36 >"${config_dir}/auto-auth-password.tmp"
  mv "${config_dir}/auto-auth-password.tmp" "${config_dir}/auto-auth-password"
fi

if [[ ! -s "${config_dir}/jwks-key" ]]; then
  /bin/node /opt/lobehub/create-jwks.js >"${config_dir}/jwks-key.tmp"
  mv "${config_dir}/jwks-key.tmp" "${config_dir}/jwks-key"
fi

if [[ "$(psql --username=postgres --dbname=postgres --tuples-only --no-align \
  --command="SELECT 1 FROM pg_database WHERE datname = 'lobehub'")" != "1" ]]; then
  createdb --username=postgres --owner=postgres lobehub
fi

if [[ -z ${APP_URL:-} ]]; then
  echo "APP_URL is required" >&2
  exit 1
fi
export APP_URL
export AUTH_ALLOWED_EMAILS="${auto_auth_email}"
export AUTH_SECRET
AUTH_SECRET=$(<"${config_dir}/auth-secret")
export DATABASE_URL="postgresql://postgres@127.0.0.1:5432/lobehub"
export HOSTNAME=127.0.0.1
export INTERNAL_APP_URL="http://127.0.0.1:8081"
export JWKS_KEY
JWKS_KEY=$(<"${config_dir}/jwks-key")
export KEY_VAULTS_SECRET
KEY_VAULTS_SECRET=$(<"${config_dir}/key-vaults-secret")
export PORT=8081

cd /app
exec s6-setuidgid nextjs /bin/node /app/startServer.js
