#!/usr/bin/env bash
# 用途: 把 dotfiles 里导出的 workflow JSON 文件导入回 Warp 本地 SQLite。
# 说明: 该版本 Warp 从 group container 的 warp.sqlite 读取 workflow。
#       导入会 **整表重建** workflows 表 (先清空再插入), 因为 workflow 无稳定 uuid、
#       name 可能重复, 整表重建是唯一可预测的方式。
# 安全: 导入前要求 Warp 已退出, 并自动备份数据库到 <db>.bak.<时间戳>。
# Usage: import.sh [input_dir]
#   input_dir  JSON 目录, 默认为脚本同级的 workflows/
# 依赖: sqlite3, jq
# Shell dialect: bash (兼容 macOS 自带 3.2)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR
readonly DEFAULT_DB="$HOME/Library/Group Containers/2BBY89MBSN.dev.warp/Library/Application Support/dev.warp.Warp-Stable/warp.sqlite"

log() { printf '%s [%s] %s\n' "$(date '+%H:%M:%S')" "$1" "${*:2}" >&2; }

# SQL 单引号转义: ' -> ''
sql_quote() { printf "%s" "$1" | sed "s/'/''/g"; }

# 临时 SQL 文件用全局变量, 以便 EXIT trap 在 main 返回后仍能清理。
SQL_FILE=""
cleanup() { [[ -n "$SQL_FILE" ]] && rm -f "$SQL_FILE"; }
trap cleanup EXIT

main() {
  local db="${WARP_DB:-$DEFAULT_DB}"
  local in_dir="${1:-$SCRIPT_DIR/workflows}"

  command -v sqlite3 >/dev/null || { log ERROR "缺少 sqlite3"; exit 1; }
  command -v jq >/dev/null || { log ERROR "缺少 jq"; exit 1; }
  [[ -f "$db" ]] || { log ERROR "找不到数据库: $db"; exit 1; }
  [[ -d "$in_dir" ]] || { log ERROR "找不到输入目录: $in_dir"; exit 1; }

  # Warp 运行时写 WAL, 直接改真实库会被覆盖或损坏, 故要求先退出。
  # 仅对默认真实库做此检查; 通过 WARP_DB 指定其它库 (如测试副本) 时跳过。
  if [[ "$db" == "$DEFAULT_DB" ]] && pgrep -f "Warp.app/Contents/MacOS/stable" >/dev/null; then
    log ERROR "检测到 Warp 正在运行, 请先完全退出 Warp (Cmd+Q) 再导入"
    exit 1
  fi

  local files=()
  while IFS= read -r -d '' f; do files+=("$f"); done \
    < <(find "$in_dir" -maxdepth 1 -type f -name '*.json' -print0)

  if [[ ${#files[@]} -eq 0 ]]; then
    log WARN "目录内没有 *.json, 无可导入内容"
    return 0
  fi

  # 先校验所有 JSON 合法, 再动数据库 (fail-fast)。
  local f
  for f in "${files[@]}"; do
    if ! jq empty "$f" 2>/dev/null; then
      log ERROR "非法 JSON: $f, 已中止 (未改动数据库)"
      exit 1
    fi
  done

  # 备份数据库 (含 WAL/SHM)。
  local ts backup
  ts="$(date '+%Y%m%d-%H%M%S')"
  backup="$db.bak.$ts"
  cp "$db" "$backup"
  [[ -f "$db-wal" ]] && cp "$db-wal" "$backup-wal" || true
  [[ -f "$db-shm" ]] && cp "$db-shm" "$backup-shm" || true
  log INFO "已备份数据库到 $backup"

  # 拼 SQL 写入临时文件再执行, 避免 printf '%b' 二次解释命令里的 \n / \\ 破坏数据。
  SQL_FILE="$(mktemp)"

  {
    printf 'BEGIN TRANSACTION;\n'
    printf 'DELETE FROM workflows;\n'
  } >"$SQL_FILE"

  local data quoted count=0
  for f in "${files[@]}"; do
    data="$(jq -c . "$f")"
    quoted="$(sql_quote "$data")"
    printf "INSERT INTO workflows (data) VALUES ('%s');\n" "$quoted" >>"$SQL_FILE"
    count=$((count + 1))
  done
  printf 'COMMIT;\n' >>"$SQL_FILE"

  sqlite3 "$db" <"$SQL_FILE"
  log INFO "导入完成, 共写入 $count 条 workflow"
  log INFO "重启 Warp 后即可看到; 如有异常可用备份恢复: cp '$backup' '$db'"
}

main "$@"
