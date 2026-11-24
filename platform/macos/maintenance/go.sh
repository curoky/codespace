#!/usr/bin/env bash
set -euo pipefail

version="1.27.1"
expected_sha256="ee215d57e0ec269c60cc9ceca68e6bda321ba9ee5afe24f4b0988703c2d87d12"
destination="$HOME/.local/opt/go/go${version}"
marker="$destination/.codespace-version"

if [[ -x "$destination/bin/go" && -f "$marker" ]] &&
  [[ "$(<"$marker")" == "$version" ]]; then
  exit 0
fi

work_dir="$(mktemp -d)"
archive="$work_dir/go.tar.gz"
trap 'rm -rf "$work_dir"' EXIT

curl -fsSL "https://go.dev/dl/go${version}.darwin-arm64.tar.gz" -o "$archive"
actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
if [[ "$actual" != "$expected_sha256" ]]; then
  printf 'error: Go %s checksum mismatch\n' "$version" >&2
  exit 1
fi

rm -rf "${destination}.installing"
mkdir -p "${destination}.installing"
tar -xf "$archive" --strip-components=1 -C "${destination}.installing"
printf '%s\n' "$version" >"${destination}.installing/.codespace-version"
rm -rf "$destination"
mv "${destination}.installing" "$destination"
