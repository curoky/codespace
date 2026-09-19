#!/usr/bin/env bash

set -euo pipefail

export CHATBOX_API_UPSTREAM=http://codespace-service-sglang:8080

config_dir=/tmp/chatbox/nginx/conf.d
mkdir -p "${config_dir}"
envsubst "\${CHATBOX_API_UPSTREAM}" \
  </etc/nginx/templates/default.conf.template \
  >"${config_dir}/default.conf"

exec nginx -c /opt/chatbox/nginx.conf -g "daemon off;"
