#!/usr/bin/env bash

# Personal encrypted JSON store; Bash 3.2+, gpg, jq; macOS also requires yq.

check_arguments() {
  local usage='Usage: csecret {get KEY|encrypt|decrypt}'
  case "${1:-}" in
    -h | --help)
      printf '%s\n' "$usage"
      exit 0
      ;;
    get)
      [[ $# == 2 ]] && return
      ;;
    encrypt | decrypt)
      [[ $# == 1 ]] && return
      ;;
  esac
  printf '%s\n' "$usage" >&2
  exit 2
}

read_passphrase() {
  case "$(uname -s)" in
    Linux)
      cat /run/secrets/codespace_workspace_key
      ;;
    Darwin)
      if ! yq eval-all --yaml-fix-merge-anchor-to-spec -e -r '
        [.] | select(length == 1) | .[0].secrets.codespace_workspace_key |
          explode(.) | select(tag == "!!str") | select(trim != "")
      ' "$HOME/.config/codespace/config.yaml" 2>/dev/null; then
        printf 'error: cannot read codespace_workspace_key from Codespace config\n' >&2
        return 1
      fi
      ;;
    *)
      printf 'error: unsupported csecret platform\n' >&2
      return 1
      ;;
  esac
}

run_gpg() {
  printf '%s' "$passphrase" |
    gpg --no-options --homedir "$gpg_home" --quiet --batch --no-autostart \
      --pinentry-mode loopback --no-symkey-cache --passphrase-fd 0 "$@"
}

write_store() {
  local target="$1"
  shift
  temporary="$(mktemp "$target.XXXXXX")"
  run_gpg --yes --output "$temporary" "$@"
  mv -- "$temporary" "$target"
  temporary=
}

# shellcheck disable=SC2329 # Invoked by the EXIT trap in main.
cleanup() {
  [[ -z "$temporary" ]] || rm -f -- "$temporary"
  [[ -z "$gpg_home" ]] || rm -rf -- "$gpg_home"
}

# A subshell keeps local cleanup state alive when errexit unwinds the function.
main() (
  set -euo pipefail
  umask 077
  if ((BASH_VERSINFO[0] < 3 || (BASH_VERSINFO[0] == 3 && BASH_VERSINFO[1] < 2))); then
    printf 'error: Bash 3.2 or newer is required\n' >&2
    exit 1
  fi
  check_arguments "$@"

  local directory passphrase gpg_home='' temporary=''
  directory="$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")"
  passphrase="$(read_passphrase)"
  trap 'cleanup' EXIT
  gpg_home="$(mktemp -d)"

  case "$1" in
    get)
      run_gpg --decrypt "$directory/secrets.json.gpg" |
        jq -j --arg key "$2" 'if has($key) then .[$key] else error("secret not found: " + $key) end'
      ;;
    encrypt)
      jq -e 'type == "object"' "$directory/secrets.json" >/dev/null
      # A fixed S2K count avoids starting gpg-agent for passphrase calibration.
      write_store "$directory/secrets.json.gpg" --cipher-algo AES256 --s2k-count 65011712 \
        --symmetric "$directory/secrets.json"
      ;;
    decrypt)
      write_store "$directory/secrets.json" --decrypt "$directory/secrets.json.gpg"
      ;;
  esac
)

main "$@"
