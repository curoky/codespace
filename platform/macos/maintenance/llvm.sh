#!/usr/bin/env bash
set -euo pipefail

version="23.1.2"
expected_sha256="d7c26fc6177e42842e2d1ffaad31aec057c56a924392b1a23d830abe2c5d53b1"
destination="$HOME/.local/opt/llvm/llvm${version}"
marker="$destination/.codespace-version"

if [[ -x "$destination/bin/clang" && -x "$destination/bin/clang-format" && -f "$marker" ]] &&
  [[ "$(<"$marker")" == "$version" ]]; then
  ln -sfn "llvm${version}" "${destination%/*}/llvm${version%%.*}"
  exit 0
fi

work_dir="$(mktemp -d)"
archive="$work_dir/llvm.tar.xz"
trap 'rm -rf "$work_dir" "${destination}.installing"' EXIT

curl -fsSL \
  "https://github.com/llvm/llvm-project/releases/download/llvmorg-${version}/LLVM-${version}-macOS-ARM64.tar.xz" \
  -o "$archive"
actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
if [[ "$actual" != "$expected_sha256" ]]; then
  printf 'error: LLVM %s checksum mismatch\n' "$version" >&2
  exit 1
fi

rm -rf "${destination}.installing"
mkdir -p "${destination}.installing"
tar -xJf "$archive" --strip-components=1 -C "${destination}.installing"
for executable in clang clang++ clang-format clangd llvm-config; do
  test -x "${destination}.installing/bin/$executable"
done
printf '%s\n' "$version" >"${destination}.installing/.codespace-version"
rm -rf "$destination"
mv "${destination}.installing" "$destination"
ln -sfn "llvm${version}" "${destination%/*}/llvm${version%%.*}"
