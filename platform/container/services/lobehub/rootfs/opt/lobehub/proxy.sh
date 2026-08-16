#!/usr/bin/env bash

set -euo pipefail

data_root="${LOBEHUB_DATA_DIR:-/var/lib/codespace/lobehub}"
password_file="${data_root}/config/auto-auth-password"

if [[ ! -s "${password_file}" ]]; then
  echo "automatic authentication password is missing: ${password_file}" >&2
  exit 1
fi

export LOBEHUB_AUTO_AUTH_EMAIL="codespace@codespace.invalid"
export LOBEHUB_AUTO_AUTH_PASSWORD
LOBEHUB_AUTO_AUTH_PASSWORD=$(<"${password_file}")

exec s6-setuidgid nextjs /bin/node /opt/lobehub/auth-proxy.js
