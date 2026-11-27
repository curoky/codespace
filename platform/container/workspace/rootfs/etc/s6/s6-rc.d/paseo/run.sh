#!/usr/bin/env bash
set -euo pipefail

# shellcheck source-path=SCRIPTDIR source=../../../profile.d/app.sh
source /etc/profile.d/app.sh

PASEO_PASSWORD="$(/home/x/.local/bin/csecret get paseo_password)"
export PASEO_PASSWORD
# Match Paseo's own trimming so a blank secret cannot disable authentication.
if ! node -e 'if (!process.env.PASEO_PASSWORD?.trim()) process.exit(1)'; then
  printf '%s\n' 'Paseo requires a nonblank paseo_password secret' >&2
  exit 1
fi
exec /home/x/.local/opt/node/tools/bin/paseo daemon run
