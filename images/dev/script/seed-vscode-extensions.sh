#!/usr/bin/env bash

# 把构建期预装的 VSCode 扩展播种到各 IDE 远端 server 的扩展目录。
#
# 背景：home-init.sh 启动时把 ~/.vscode-server、~/.trae-server、~/.trae-cn-server 软链到
# 持久化的 /workspace/.cache，因此扩展不能烤进镜像的 ~/.vscode-server（首启会被 rm -rf
# 清掉），只能在启动时按工作区播种。构建期的参考副本见 setup-vscode-extensions.sh。
#
# 用法：seed-vscode-extensions.sh <server_dir> [server_dir...]
#   每个 server_dir 首启只播种一次（marker 存在即跳过），之后用户自行管理扩展；删掉
#   marker 可重新播种。Trae/Trae CN 复用同一份 VSCode 扩展副本。
#   参考副本路径可用 REF_EXTENSIONS 覆盖，默认 /opt/vscode-extensions/extensions。

set -euo pipefail

REF_EXTENSIONS=${REF_EXTENSIONS:-/opt/vscode-extensions/extensions}

function seed_extensions() {
  local server_dir="$1"
  local target="$server_dir/extensions"
  local marker="$server_dir/.devspace-extensions-seeded"

  [[ -d $REF_EXTENSIONS ]] || return 0
  [[ -f $marker ]] && return 0

  mkdir -p "$target"

  # 合并前先读取用户已有的 installed manifest，避免被覆盖。
  local target_json="$target/extensions.json"
  local existing='[]'
  [[ -f $target_json ]] && existing="$(< "$target_json")"

  # 复制扩展目录，-n 不覆盖用户已装的同名扩展。
  cp -rn "$REF_EXTENSIONS"/. "$target"/ 2>/dev/null || true

  # 重写参考 manifest 里的 location 为 target 绝对路径，再按 identifier.id 去重合并到用户
  # 已有列表（用户版本优先），最后写回 target 的 installed manifest。
  local ref_json="$REF_EXTENSIONS/extensions.json"
  if [[ -f $ref_json ]]; then
    local rewritten merged
    rewritten="$(/opt/sb/bin/jq --arg dir "$target" \
      'map((.relativeLocation // (.location.path | sub(".*/"; ""))) as $rel
           | .relativeLocation = $rel
           | .location = {"$mid":1,"path":($dir + "/" + $rel),"scheme":"file"})' \
      "$ref_json")"
    merged="$(/opt/sb/bin/jq -n \
      --argjson existing "$existing" \
      --argjson ref "$rewritten" \
      '($existing | map(.identifier.id)) as $have
       | $existing + ($ref | map(select((.identifier.id) as $id | ($have | index($id)) | not)))')"
    printf '%s\n' "$merged" >"$target_json"
  fi

  touch "$marker"
}

for server_dir in "$@"; do
  seed_extensions "$server_dir"
done
