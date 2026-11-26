#!/usr/bin/env bash
set -euo pipefail
umask 077

job_dir=$(mktemp -d /home/x/.codex/.custom-job.XXXXXX)
trap 'rm -rf -- "$job_dir"' EXIT

content=$(cat /home/x/.codex/llmbox.config.toml.template)
for key in OAUTH_DOMAIN MODEL_DOMAIN OAUTH_CLIENT_ID LLMBOX_SOURCE; do
  value=$(/home/x/.local/bin/csecret get "$key")
  content=${content//@${key}@/$value}
done
download_url=$(/home/x/.local/bin/csecret get traecli_download_curl)
printf '%s\n' "$content" >"$job_dir/llmbox.config.toml"

mv -f -- "$job_dir/llmbox.config.toml" /home/x/.codex/llmbox.config.toml
curl -fsSL "$download_url" | /bin/sh
