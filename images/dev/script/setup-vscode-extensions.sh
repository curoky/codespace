#!/usr/bin/env bash

# 构建期预装 VSCode Remote 扩展。
#
# 官方 VSCode Remote-SSH 会在远端 ~/.vscode-server 下放一份 reh（remote extension
# host）server，并把扩展装到 ~/.vscode-server/extensions。运行期 Controller 会把
# host cache 下的对应目录直接挂载到 ~/.vscode-server 等路径，因此扩展不能直接烤进
# 镜像中的这些目录。
#
# 本脚本在构建期用官方 code-server 把 extensions.txt 里的扩展装进一份镜像内的参考副本
# （默认 /opt/vscode-extensions/extensions），运行期由 seed-vscode-extensions 播种到
# 各 IDE server 的工作区扩展目录。server 二进制只是构建期一次性工具，装完即弃。

set -xeuo pipefail

ext_list=${1:?usage: setup-vscode-extensions.sh <extensions.txt> [dest_dir]}
dest_dir=${2:-/opt/vscode-extensions}

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

# UI/客户端专属扩展（remote-ssh、主题、keymap 等）不进 remote server，由 extensions.txt
# 直接排除——该文件是唯一事实来源，本脚本不再二次过滤。

extensions_dir="$dest_dir/extensions"
mkdir -p "$extensions_dir"

ids=()
while IFS= read -r line || [[ -n $line ]]; do
  id="${line%%#*}"                     # 去掉行内注释
  id="$(echo "$id" | tr -d '[:space:]')"
  [[ -z $id ]] && continue
  ids+=("$id")
done < "$ext_list"

# 隔离到临时 HOME，避免 server 把默认 user-data / 日志写进 /home/x（首启会被清理，且会污染镜像）。
run_install() {
  env HOME="$tmp/home" "$code_server" \
    --extensions-dir "$extensions_dir" \
    --force \
    "$@"
}

# code-server 支持一次传多个 --install-extension；批量失败时逐个兜底，坏掉的扩展不阻塞其余。
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
