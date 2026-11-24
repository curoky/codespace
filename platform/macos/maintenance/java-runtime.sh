#!/usr/bin/env bash
set -euo pipefail

version="27.0.1.1+4"
expected_sha256="bd5ff11de5e247372e8b27df700938bd02fe8fe81e24cd297e1daeb027d3151b"
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
  https://github.com/adoptium/temurin27-binaries/releases/download/jdk-27.0.1.1%2B4/OpenJDK27U-jdk_aarch64_mac_hotspot_27.0.1.1_4.tar.gz \
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
