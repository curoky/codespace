#!/usr/bin/env bash
set -euo pipefail
umask 077

job_dir=$(mktemp -d /home/x/.codex/.custom-job.XXXXXX)
trap 'rm -rf -- "$job_dir"' EXIT

cat /run/secrets/codespace_workspace_key | /usr/local/bin/gpg \
  --no-options --homedir "$job_dir" --batch --no-autostart \
  --pinentry-mode loopback --no-symkey-cache --passphrase-fd 0 \
  --output "$job_dir/identifiers.sh" --decrypt /etc/s6/s6-rc.d/custom-job/identifiers.sh.gpg
# shellcheck disable=SC1091
source "$job_dir/identifiers.sh"

for template in /home/x/.codex/llmbox.config.toml.template /etc/s6/s6-rc.d/custom-job/install.sh.template; do
  content=$(cat "$template")
  content=${content//@OAUTH_DOMAIN@/$OAUTH_DOMAIN}
  content=${content//@MODEL_DOMAIN@/$MODEL_DOMAIN}
  content=${content//@INSTALL_DOMAIN@/$INSTALL_DOMAIN}
  content=${content//@OAUTH_CLIENT_ID@/$OAUTH_CLIENT_ID}
  content=${content//@LLMBOX_SOURCE@/$LLMBOX_SOURCE}
  printf '%s\n' "$content" >"$job_dir/$(basename "$template" .template)"
done

mv -f -- "$job_dir/llmbox.config.toml" /home/x/.codex/llmbox.config.toml
/bin/sh "$job_dir/install.sh"
