#!/usr/bin/env bash

# Personal GPG-encrypted JSON store; requires Bash, gpg and jq.
set -euo pipefail
umask 077

usage='Usage: csecret {get KEY|encrypt|decrypt}'
case "${1:-}" in
  -h | --help)
    printf '%s\n' "$usage"
    exit 0
    ;;
  get)
    [[ $# == 2 ]] || {
      printf '%s\n' "$usage" >&2
      exit 2
    }
    ;;
  encrypt | decrypt)
    [[ $# == 1 ]] || {
      printf '%s\n' "$usage" >&2
      exit 2
    }
    ;;
  *)
    printf '%s\n' "$usage" >&2
    exit 2
    ;;
esac

directory="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
home="$(mktemp -d)"
temporary=
trap 'rm -rf -- "$home"; [[ -z "$temporary" ]] || rm -f -- "$temporary"' EXIT
gpg=(gpg --no-options --homedir "$home" --quiet --batch --no-autostart
  --pinentry-mode loopback --no-symkey-cache
  --passphrase-file /run/secrets/codespace_workspace_key)

case "$1" in
  get)
    "${gpg[@]}" --decrypt "$directory/secrets.json.gpg" |
      jq -j --arg key "$2" 'if has($key) then .[$key] else error("secret not found: " + $key) end'
    ;;
  encrypt)
    jq -e 'type == "object"' "$directory/secrets.json" >/dev/null
    temporary="$(mktemp "$directory/secrets.json.gpg.XXXXXX")"
    # A fixed S2K count avoids starting gpg-agent for passphrase calibration.
    "${gpg[@]}" --yes --cipher-algo AES256 --s2k-count 65011712 \
      --output "$temporary" --symmetric "$directory/secrets.json"
    mv -- "$temporary" "$directory/secrets.json.gpg"
    temporary=
    ;;
  decrypt)
    temporary="$(mktemp "$directory/secrets.json.XXXXXX")"
    "${gpg[@]}" --yes --output "$temporary" --decrypt "$directory/secrets.json.gpg"
    mv -- "$temporary" "$directory/secrets.json"
    temporary=
    ;;
esac
