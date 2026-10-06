#!/usr/bin/env bash
set -euo pipefail

install_v2_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

# Reuse the unchanged installer while replacing its online binman stage.
# shellcheck source=platform/macos/install.sh
source "$install_v2_dir/install.sh"

readonly bm_artifact_type="application/vnd.curoky.codespace.macos-bm.v1"
readonly bm_layer_type="application/vnd.curoky.codespace.macos-bm.layer.v1+tar+gzip"

download_binman_bundle() {
  local output="$1"
  local reference="${CODESPACE_BM_REFERENCE:-macos-bm-darwin-arm64}"
  local registry_token manifest layer_digest layer_type expected actual ghcr_username
  local work_dir
  work_dir="$(dirname "$output")"

  local -a credentials=()
  if [[ -n "${GHCR_TOKEN:-}" ]]; then
    ghcr_username="${GHCR_USERNAME:-${GITHUB_ACTOR:-}}"
    if [[ -z "$ghcr_username" ]]; then
      printf 'error: GHCR_USERNAME is required when GHCR_TOKEN is set\n' >&2
      return 1
    fi
    credentials=(-u "$ghcr_username:$GHCR_TOKEN")
  fi

  curl -fsSL "${credentials[@]}" \
    'https://ghcr.io/token?service=ghcr.io&scope=repository:curoky/codespace:pull' \
    -o "$work_dir/token.json"
  registry_token="$(/usr/bin/plutil -extract token raw -o - "$work_dir/token.json")"
  if [[ -z "$registry_token" ]]; then
    printf 'error: GHCR returned an empty registry token\n' >&2
    return 1
  fi

  manifest="$work_dir/manifest.json"
  curl -fsSL \
    -H "Authorization: Bearer $registry_token" \
    -H 'Accept: application/vnd.oci.image.manifest.v1+json' \
    "https://ghcr.io/v2/curoky/codespace/manifests/$reference" \
    -o "$manifest"

  if [[ "$(/usr/bin/plutil -extract artifactType raw -o - "$manifest")" != "$bm_artifact_type" ]]; then
    printf 'error: GHCR artifact has an unexpected type\n' >&2
    return 1
  fi
  if /usr/bin/plutil -extract layers.1.digest raw -o - "$manifest" >/dev/null 2>&1; then
    printf 'error: GHCR artifact must contain exactly one layer\n' >&2
    return 1
  fi

  layer_digest="$(/usr/bin/plutil -extract layers.0.digest raw -o - "$manifest")"
  layer_type="$(/usr/bin/plutil -extract layers.0.mediaType raw -o - "$manifest")"
  if [[ "$layer_type" != "$bm_layer_type" || "$layer_digest" != sha256:* ]]; then
    printf 'error: GHCR artifact has an unexpected layer\n' >&2
    return 1
  fi

  curl -fsSL \
    -H "Authorization: Bearer $registry_token" \
    "https://ghcr.io/v2/curoky/codespace/blobs/$layer_digest" \
    -o "$output"

  expected="${layer_digest#sha256:}"
  actual="$(shasum -a 256 "$output" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    printf 'error: bm bundle digest mismatch\n' >&2
    return 1
  fi
}

install_binman_bundle() {
  local archive="$1"
  local destination="${2:-/opt/bm}"
  local entries entry stage replacement

  if [[ "$destination" != /*/bm ]]; then
    printf 'error: bm destination must be an absolute path ending in /bm\n' >&2
    return 1
  fi
  if ! entries="$(tar -tzf "$archive")"; then
    printf 'error: invalid bm bundle\n' >&2
    return 1
  fi
  while IFS= read -r entry; do
    entry="${entry%/}"
    case "$entry" in
      ../* | */../* | */..)
        printf 'error: bm bundle contains an unsafe path: %s\n' "$entry" >&2
        return 1
        ;;
      bm | bm/*) ;;
      *)
        printf 'error: bm bundle contains an unexpected path: %s\n' "$entry" >&2
        return 1
        ;;
    esac
  done <<<"$entries"

  stage="$(mktemp -d)"
  tar -xzf "$archive" -C "$stage"
  if [[ ! -x "$stage/bm/bin/bm" ]]; then
    rm -rf "$stage"
    printf 'error: bm bundle does not contain an executable bin/bm\n' >&2
    return 1
  fi
  "$stage/bm/bin/bm" --help >/dev/null

  replacement="${destination}.installing"
  sudo install -d "$(dirname "$destination")"
  sudo rm -rf "$replacement"
  sudo mv "$stage/bm" "$replacement"
  sudo rm -rf "$destination"
  sudo mv "$replacement" "$destination"
  rm -rf "$stage"
  printf 'installed %s\n' "$destination"
}

install_binman() {
  local work_dir bundle
  if [[ "$(uname -s)/$(uname -m)" != "Darwin/arm64" ]]; then
    printf 'error: the packaged bm installation supports only Darwin/arm64\n' >&2
    return 1
  fi

  work_dir="$(mktemp -d)"
  bundle="$work_dir/codespace-bm-darwin-arm64.tar.gz"
  download_binman_bundle "$bundle"
  install_binman_bundle "$bundle"
  rm -rf "$work_dir"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
