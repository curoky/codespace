#!/usr/bin/env bash
# 用途: 把 Warp 本地 SQLite 里的个人 workflow 导出为逐条 JSON 文件, 便于纳入 dotfiles 做 git 管理。
# 说明: 该版本 Warp 从 group container 的 warp.sqlite 读取 workflow, 而非 ~/.warp/workflows/ 目录。
#       只导出未删除的 workflow (object_metadata.trashed_ts 为空); 回收站里的会被跳过。
#       导出为只读操作, 不修改数据库。
# Usage: export.sh [output_dir]
#   output_dir  导出目录, 默认为脚本同级的 workflows/
# 依赖: sqlite3, jq
# Shell dialect: bash (兼容 macOS 自带 3.2)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly DEFAULT_DB="$HOME/Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite"

log() { printf '%s [%s] %s\n' "$(date '+%H:%M:%S')" "$1" "${*:2}" >&2; }

# 把 workflow name 转成安全的文件名基名。
sanitize() {
  local name="$1" out
  out="$(printf '%s' "$name" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9._-' '-')"
  out="${out##-}"
  out="${out%%-}"
  printf '%s' "${out:-unnamed}"
}

main() {
  local db="${WARP_DB:-$DEFAULT_DB}"
  local out_dir="${1:-$SCRIPT_DIR/workflows}"

  command -v sqlite3 >/dev/null || { log ERROR "缺少 sqlite3"; exit 1; }
  command -v jq >/dev/null || { log ERROR "缺少 jq"; exit 1; }
  [[ -f "$db" ]] || { log ERROR "找不到数据库: $db"; exit 1; }

  mkdir -p "$out_dir"
  # 清空旧的导出结果, 保证幂等 (重复运行不堆积 -2/-3 后缀)。
  find "$out_dir" -maxdepth 1 -type f -name '*.json' -delete

  local ids id data name base file
  # 只导出未删除的 workflow: object_metadata.trashed_ts 非空表示已在回收站, 需排除。
  ids="$(sqlite3 "$db" "SELECT w.id FROM workflows w JOIN object_metadata m ON m.object_type='WORKFLOW' AND m.shareable_object_id = w.id WHERE m.trashed_ts IS NULL ORDER BY w.id;")"

  if [[ -z "$ids" ]]; then
    log WARN "没有未删除的 workflow 可导出"
    return 0
  fi

  local count=0
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    data="$(sqlite3 "$db" "SELECT data FROM workflows WHERE id=$id;")"
    if ! printf '%s' "$data" | jq empty 2>/dev/null; then
      log WARN "id=$id 的 data 不是合法 JSON, 已跳过"
      continue
    fi
    name="$(printf '%s' "$data" | jq -r '.name // "unnamed"')"
    base="$(sanitize "$name")"

    # 文件名冲突直接 fail-fast: 加后缀会导致导入重复堆积, 宁可报错让用户先改名。
    file="$out_dir/$base.json"
    if [[ -e "$file" ]]; then
      log ERROR "文件名冲突: [$name] 会覆盖已有的 $base.json, 请先在 Warp 里重命名后重试"
      exit 1
    fi

    # 排序 key + 美化, 保证可复现的 diff。
    printf '%s' "$data" | jq -S . >"$file"
    log INFO "导出 [$name] -> $base.json"
    count=$((count + 1))
  done <<<"$ids"

  log INFO "完成, 共导出 $count 条到 $out_dir"
}

main "$@"
