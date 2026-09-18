#!/usr/bin/env bash

set -euo pipefail

readonly root=/srv
readonly pass_file=/run/secrets/secret_webdav_password

if [[ ! -r ${pass_file} ]]; then
  echo "secret WebDAV password is missing: ${pass_file}" >&2
  exit 1
fi
password="$(<"${pass_file}")"

mkdir -p -- "${root}"

exec /opt/bm/store/rclone/bin/rclone serve webdav "${root}" \
  --addr "0.0.0.0:8080" \
  --user codespace \
  --pass "${password}" \
  --etag-hash MD5 \
  --dir-cache-time 10s \
  --stats 0
