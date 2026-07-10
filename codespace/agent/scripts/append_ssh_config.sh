#!/bin/sh
# Idempotently merge the codespace-managed git ssh config block into
# ~/.ssh/config. Run via `sh -c <script> append-ssh-config <ssh_dir> <begin>
# <end>` from codespace.agent.credentials, so the positional args are:
#   $1  ssh_dir     login user's ~/.ssh directory
#   $2  begin_marker  managed-block begin sentinel
#   $3  end_marker    managed-block end sentinel
# The new block content is staged at $ssh_dir/config.codespace.tmp.
set -eu
ssh_dir="$1"
config="$ssh_dir/config"
tmp_block="$ssh_dir/config.codespace.tmp"
tmp_config="$ssh_dir/config.codespace.new"
begin_marker="$2"
end_marker="$3"
touch "$config"
awk '
  $0 == begin { skipping = 1; next }
  $0 == end { skipping = 0; next }
  !skipping { print }
' begin="$begin_marker" end="$end_marker" "$config" > "$tmp_config"
if [ -s "$tmp_config" ] && [ "$(tail -c 1 "$tmp_config")" != "" ]; then
  printf '\n' >> "$tmp_config"
fi
cat "$tmp_block" >> "$tmp_config"
mv "$tmp_config" "$config"
rm -f "$tmp_block"
chmod 600 "$config"
