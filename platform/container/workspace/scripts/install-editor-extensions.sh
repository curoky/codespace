#!/usr/bin/env bash

# 构建 immutable VSCode Remote extension template。运行期持久 mount 会遮蔽 IDE
# extension 目录，因此 template 独立于 image home；code-server 仅作构建工具。

set -xeuo pipefail

ext_list=${1:?usage: install-editor-extensions.sh <extensions.txt> <dest_dir>}
dest_dir=${2:?usage: install-editor-extensions.sh <extensions.txt> <dest_dir>}

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

server_url="https://update.code.visualstudio.com/latest/server-linux-${server_arch}/stable"
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

batch_args=()
for id in "${ids[@]}"; do
  batch_args+=("--install-extension" "$id")
done

# 缺少声明的扩展直接使构建失败，不发布部分安装的 template。
env HOME="$tmp/home" "$code_server" \
  --extensions-dir "$extensions_dir" --force "${batch_args[@]}"

# 所有 IDE 的目标路径在 image contract 中固定，运行期只复制对应 manifest。
for server in .vscode-server .trae-server .trae-cn-server; do
  jq --arg dir "/home/x/$server/extensions" \
    'map((.location.path | split("/") | last) as $rel
         | .relativeLocation = $rel
         | .location = {"$mid":1,"path":($dir + "/" + $rel),"scheme":"file"})' \
    "$extensions_dir/extensions.json" >"$dest_dir/$server.json"
done
rm "$extensions_dir/extensions.json"
