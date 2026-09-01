#!/usr/bin/env bash

set -euo pipefail

link_cache_dir() {
  local name=$1
  local cache_dir="/cache/${name}"
  local home_dir="/home/x/${name}"

  mkdir -p -- "${cache_dir}"
  rm -rf -- "${home_dir}"
  ln -s -- "${cache_dir}" "${home_dir}"
}

main() {
  if [[ $# -ne 0 ]]; then
    echo "usage: home-links-init.sh" >&2
    return 2
  fi

  link_cache_dir .vscode-server
  link_cache_dir .trae
  link_cache_dir .trae-cn
  link_cache_dir .trae-server
  link_cache_dir .trae-cn-server
}

main "$@"
