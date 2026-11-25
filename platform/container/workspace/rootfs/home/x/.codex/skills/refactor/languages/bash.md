# Bash/Shell 重构参考（详细·确定性）

> 写/改/重构/评审 Shell,或起步(0→1)选型时加载。本文件是 Bash/Shell 的完整规范:起步基线与使用边界(§0)+「旧惯用法 → 现代惯用法」改写映射 + 风格/错误清理/文本性能/测试/安全/工具链。冲突时以 `../SKILL.md` 的重构判据为准。搭建新项目/工程治理时，本文件也是 `project-setup` skill 引用的语言选型与工具链唯一真相。

## 0. 基线与边界

- **要不要用 Shell**:Shell 只做命令粘合与流程编排;出现复杂数据结构、非平凡字符串/数值处理、需单测的业务逻辑时,起步就改用 Python/Go。
- **dialect**:无额外安装环境用 `#!/bin/sh` 严格遵循 POSIX(`set -eu`);可保证现代 runtime 用官方最新稳定 Bash(落地核实),`#!/usr/bin/env bash` + `set -euo pipefail`,文件头注明最低版本并在入口用 `BASH_VERSINFO` 校验,不满足向 stderr 报错退出。
- 以下未标注 POSIX 的语法/实践仅适用于 Bash;写 `#!/bin/sh` 时只用 POSIX 定义的语法与工具行为。
- Shell 无第三方依赖库生态;可复用逻辑拆到 `lib/*.sh` 用 `source`/`.` 引入,被 source 文件不写顶层副作用。

## 现代化改写映射（旧 → 新）

- 反引号 `` `cmd` `` → `$(cmd)`。
- `[ ... ]` 测试 → Bash 用 `[[ ... ]]`；数值比较用 `(( ... ))`。
- `eval` 拼命令 → 参数数组 `cmd "${args[@]}"`。
- 解析 `ls` 输出 → glob 或 `find -print0` + `mapfile`/`xargs -0`。
- 无引号变量展开 → `"$var"`、`"${arr[@]}"`。
- `expr` 算术 → `$(( ... ))`。
- `cat file | cmd` → `cmd < file`。
- 逐行 Bash 循环调外部命令 → `awk`/`grep`/`sort` 一次性处理。
- 固定临时路径 → `mktemp`/`mktemp -d` + `trap ... EXIT`。
- 复杂数据/逻辑塞进 Shell → 改用 Python/Go。

## 1. 风格与结构

- 函数和局部变量 `snake_case`；常量和导出环境变量 `UPPER_SNAKE_CASE`；只读常量用 `readonly`/`declare -r`。
- 变量展开默认加引号：`"$var"`、`"${arr[@]}"`；确需词分割/glob 时显式说明。
- 函数内变量用 `local`；格式用 `shfmt`。
- 用 `main "$@"` 作为入口；顶层只做定义和 `main "$@"` 调用。
- 位置参数用 `"$1"`/`"$@"`；短选项用 `getopts`；复杂 CLI 改用其他语言。
- 可复用逻辑放 `lib/*.sh` 并用 `source`/`.` 引入；被 source 的文件不写顶层副作用。

## 2. 错误、清理、子进程

- 保持 §0 对应 shell dialect 的严格模式；容错命令用显式判断或局部 `|| true`，不全局关闭严格模式。
- 临时文件、后台进程用 `trap 'cleanup' EXIT` 或 `trap ... ERR` 清理。
- 外部命令先 `command -v tool >/dev/null` 校验；参数缺失/非法时向 stderr 输出用法并非零退出。
- 成功 `exit 0`；失败用有区分度的非零码。正常结果输出 stdout，错误/日志输出 stderr。
- `&` 启动的后台任务必须 `wait`/`wait -n` 回收并捕获退出码。
- 批量并行优先 `xargs -P N -0`（配 `find -print0`）或 GNU `parallel`；避免无上限 `&`。
- 管道和 `( ... )` 会开子 shell；需要变量回传时用进程替换 `< <(...)` 或 `mapfile`。

## 3. 文本处理与性能

- 能用 Bash 内建就不 fork 外部命令：参数展开、`[[ ]]`、`(( ))`。
- 大文本批处理交给 `awk`/`grep`/`sort` 等一次性处理；避免逐行 Bash 循环里反复调外部命令。
- 避免 `cat file | cmd`；用 `cmd < file` 或让命令直接读文件。

## 4. 注释与测试

- 文件头写脚本用途、`Usage:`、外部命令依赖、shell dialect；Bash 脚本另写最低版本。
- 非平凡函数注释入参、全局副作用、返回约定；注释写意图，不复述命令。
- 测试用 `bats-core`；可测逻辑拆成函数后在测试中 `source`。
- `shellcheck` 零告警是最低门槛。
- 测试用 `mktemp -d`，通过 `PATH` 前置桩 mock 外部命令；不依赖真实网络/全局状态。

## 5. 安全与日志

- 外部输入当不可信数据；所有展开加引号防词分割和 glob。
- 禁止 `eval` 和拼接未过滤输入；调用命令用参数数组：`cmd "${args[@]}"`。
- 路径/参数用 `--` 终结选项，避免选项注入。
- 临时文件用 `mktemp`/`mktemp -d`，配 `trap ... EXIT`；不用可预测固定路径。
- 密钥/令牌不硬编码、不打日志。调试 `set -x` 注意敏感信息，用完 `set +x`。
- 非平凡脚本日志带时间戳与级别；批量循环避免逐条刷屏。
- 错误日志带命令、目标路径/参数、退出码。

## 6. 工具链

| 用途 | 工具 |
| --- | --- |
| 格式化 | `shfmt`，如 `shfmt -i 2 -ci`。 |
| Lint/静态分析 | `shellcheck`，CI 零告警。 |
| 测试 | `bats-core`，可配 `bats-assert`/`bats-support`。 |

- pre-commit 用 `lefthook`：对暂存 `*.sh`/`*.bash` 跑 `shfmt -d` 或 `-l`、`shellcheck`；CI 重复执行并运行 `bats`。
