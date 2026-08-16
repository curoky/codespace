#!/usr/bin/env bash

set -euo pipefail

envsubst "\${CHATBOX_API_UPSTREAM}" \
  </etc/nginx/templates/default.conf.template \
  >/etc/nginx/conf.d/default.conf

exec nginx -g "daemon off;"
