#!/usr/bin/env bash
set -euo pipefail

version="27+35"
expected_sha256="a59626c926f0146a286cb535fc9a46499d6c46b3d79ae72168bbf18438fe49dd"
destination="$HOME/.local/opt/java/openjdk27"
marker="$destination/.codespace-version"

if [[ -x "$destination/bin/java" && -x "$destination/bin/javac" && -f "$marker" ]] &&
  [[ "$(<"$marker")" == "$version" ]]; then
  exit 0
fi

work_dir="$(mktemp -d)"
archive="$work_dir/jdk.tar.gz"
trap 'rm -rf "$work_dir"' EXIT

curl -fsSL \
  https://github.com/adoptium/temurin27-binaries/releases/download/jdk-27%2B35/OpenJDK27U-jdk_aarch64_mac_hotspot_27_35.tar.gz \
  -o "$archive"
actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
if [[ "$actual" != "$expected_sha256" ]]; then
  printf 'error: Java %s checksum mismatch\n' "$version" >&2
  exit 1
fi

mkdir -p "$work_dir/jdk" "$(dirname "$destination")"
# Temurin's macOS bundle wraps the runtime in Contents/Home.
tar -xzf "$archive" --strip-components=3 -C "$work_dir/jdk" "jdk-${version}/Contents/Home"
test -x "$work_dir/jdk/bin/java"
test -x "$work_dir/jdk/bin/javac"
printf '%s\n' "$version" >"$work_dir/jdk/.codespace-version"
rm -rf "$destination"
mv "$work_dir/jdk" "$destination"
