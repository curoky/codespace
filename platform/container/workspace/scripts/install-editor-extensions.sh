#!/usr/bin/env bash

# 构建 immutable VSCode Remote extension template。运行期持久 mount 会遮蔽 IDE
# extension 目录，因此 template 独立于 image home；code-server 仅作构建工具。

set -xeuo pipefail

ext_list=${1:?usage: install-editor-extensions.sh <extensions.txt> [dest_dir]}
dest_dir=${2:-/opt/editor-extensions}

# code-server 只用于执行 --install-extension；默认取最新稳定版，可用 commit:<sha> 固定。
vscode_quality=${VSCODE_SERVER_QUALITY:-latest}
vscode_channel=${VSCODE_SERVER_CHANNEL:-stable}

case "$(uname -m)" in
  x86_64) server_arch=x64 ;;
  aarch64 | arm64) server_arch=arm64 ;;
  *)
    echo "unsupported arch: $(uname -m)" >&2
    exit 1
    ;;
esac

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

server_url="https://update.code.visualstudio.com/${vscode_quality}/server-linux-${server_arch}/${vscode_channel}"
curl -fSL "$server_url" -o "$tmp/vscode-server.tar.gz"
mkdir -p "$tmp/server"
tar -xzf "$tmp/vscode-server.tar.gz" -C "$tmp/server" --strip-components=1
code_server="$tmp/server/bin/code-server"

# 清单只包含 remote extension；本脚本不做二次分类。

extensions_dir="$dest_dir/extensions"
mkdir -p "$extensions_dir"

ids=()
while IFS= read -r line || [[ -n $line ]]; do
  id="${line%%#*}" # 去掉行内注释
  id="$(echo "$id" | tr -d '[:space:]')"
  [[ -z $id ]] && continue
  ids+=("$id")
done <"$ext_list"

# 隔离 build tool state，避免污染 image home。
run_install() {
  env HOME="$tmp/home" "$code_server" \
    --extensions-dir "$extensions_dir" \
    --force \
    "$@"
}

# 批量失败时逐个重试，单个不可用 extension 不阻塞其余项。
batch_args=()
for id in "${ids[@]}"; do
  batch_args+=("--install-extension" "$id")
done

if ! run_install "${batch_args[@]}"; then
  echo "batch install failed, retrying individually" >&2
  for id in "${ids[@]}"; do
    run_install --install-extension "$id" || echo "WARN: failed to install $id" >&2
  done
fi

ls -la "$extensions_dir"
