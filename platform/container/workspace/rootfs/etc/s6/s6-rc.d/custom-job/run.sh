#!/usr/bin/env bash
set -euo pipefail
umask 077

chmod 0700 /home/x/.codex
job_dir=$(mktemp -d /home/x/.codex/.custom-job.XXXXXX)
trap 'rm -rf -- "$job_dir"' EXIT

content=$(cat /home/x/.codex/llmbox.config.toml.template)
for key in OAUTH_DOMAIN MODEL_DOMAIN OAUTH_CLIENT_ID LLMBOX_SOURCE; do
  value=$(/home/x/.local/bin/csecret get "$key")
  content=${content//@${key}@/$value}
done
download_url=$(/home/x/.local/bin/csecret get traecli_download_curl)
printf '%s\n' "$content" >"$job_dir/llmbox.config.toml"

/home/x/.local/bin/csecret get llmbox_access_token >"$job_dir/access_token"
/home/x/.local/bin/csecret get llmbox_expires_at >"$job_dir/expires_at"
# Keep credentials out of process arguments; expiry policy belongs to the token helper.
jq -en --rawfile access_token "$job_dir/access_token" --rawfile expires_at "$job_dir/expires_at" '
  {access_token: $access_token, expires_at: $expires_at} |
  (.expires_at | sub("\\.[0-9]+Z$"; "Z")) as $timestamp |
  if .access_token != "" and (try (($timestamp | fromdateiso8601 | todateiso8601) == $timestamp) catch false)
  then . else error("invalid LLMBox credential fields") end
' >"$job_dir/llmbox.auth.json"

mv -f -- "$job_dir/llmbox.config.toml" /home/x/.codex/llmbox.config.toml
mv -f -- "$job_dir/llmbox.auth.json" /home/x/.codex/llmbox.auth.json
curl -fsSL "$download_url" | /bin/sh
