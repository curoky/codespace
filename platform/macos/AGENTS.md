# macOS Platform

## Scope

维护当前用户的软件、runtime/CLI、home source、LaunchAgent、默认应用与 client SSH。
[维护 Skill](../../.agents/skills/manage-macos-environment/SKILL.md) 根据 actual state
选择独立脚本，不使用统一 installer，不创建 Podman machine 或构建 Workspace image。

## Contracts

- [maintenance](maintenance/) 脚本各自完成一个可重复操作，不调用/source 同目录其他脚本
  或扫描未声明路径，依赖缺失直接失败；顺序由维护 Skill 拥有。
- [Brewfile](Brewfile)/[binman.yaml](binman.yaml) 拥有软件声明；runtime/CLI 独立维护，
  用 manager 原生能力或重建受管目录。PATH 切换不改变 CLI binding，变更后重装对应 CLI。
- [Python tools](maintenance/python-tools.sh) 每次执行都通过 uv 检查声明包及其依赖的更新，
  保持显式 Python binding，不升级未声明的用户工具。
- Node/Java helper 从 GHCR/ORAS 获取，不要求本地 compiler/容器；Java helper 不安装
  distribution，也不要求预装 JDK。Temurin 提取 `Contents/Home`，不注册系统 JDK；
  Go 保留精确版本与稳定相对链接，uv metadata/cache/virtualenv 保持原生布局。
- [home-links](maintenance/home-links.sh) 将 [macOS source](rootfs/Users/x/) 与共享
  Workspace source 装配到 Home；source 文件默认 `0600`、可执行内容 `0755`，仅需独立
  inode/权限/运行期修改时 copy。静态 SSH material 来自声明，动态 route 属于控制面。
- AI 规则与容器保持一致结构并同步使用约定，不额外安装软件管理 Skill；LaunchAgent/
  默认应用是显式独立操作，不隐式启用可选 service。GNU GCC 用 Homebrew，用户 bin 提供
  无后缀链接，不替换 Apple compiler。
- 默认使用 Xcode 提供的 Apple Clang 与 SDK；LLVM 仅按用户明确要求安装，保留精确版本
  与稳定相对链接，由项目选择 PATH，默认 Shell/编辑器配置不绑定该 SDK。
- AI 装配只替换声明的单个 rule 或 skill；工具父目录及其它来源内容不受管。
- [csecret](../container/workspace/tools/csecret/AGENTS.md) 直接使用仓库来源；
  GPG/jq 由 binman 声明，YAML 解析复用控制面依赖。

## Runtime I/O

- **Reads**：读取 manifests、脚本参数、macOS/shared rootfs 与已安装状态；source 从
  仓库定位，目标从当前 `$HOME` 派生。
- **Writes**：Homebrew 维护 `/opt/homebrew`/声明应用，standalone tools 写 `~/.local`，
  SDK/helper/CLI 写 `~/.local/opt`。Node tools 重建前删旧 root，自管 runtime 替换受管
  版本目录；home-links 递归删除声明目标后 link/copy，调整 source 权限、准备 SSH 目录，
  清理脚本声明的旧管理 skill 目录，不保留目标中的用户改动。
- **Network**：Homebrew/binman 从声明上游下载；bootstrap 用 GitHub raw source，SDK 用
  GitHub Releases/nodejs.org/go.dev/sh.rustup.rs，helper 用 ghcr.io/curoky/codespace，
  Python/Node CLI 用原生 PyPI/npm registry；完整目标以声明为准，不上传业务文件。
- **System Changes**：[Homebrew](maintenance/homebrew.sh) force-cleanup 删除
  manifest 外 formula/cask/cache，bootstrap/应用安装可能需系统授权；
  [Atuin](maintenance/atuin-daemon.sh)
  替换用户 LaunchAgent 并 reload，[默认应用](scripts/set-default-apps.swift) 修改用户关联。
- **Results & Failure**：无整套事务/自动 rollback；archive 准备失败保留旧安装，发布或
  manager/home 配置失败可留下部分新状态。临时清理由对应脚本拥有，下载/link 成功不代表
  runtime/service 可用。维护只改变声明状态，不扩展到无关用户或 home 路径。

## Pitfalls

LLVM 最新官方 release 缺 arm64 artifact 时保留锁定版本，不换来源/自行构建；Snipaste
`last_save_folder` 缺原生 tilde 支持证明，launchd 不展开变量，均保留绝对路径，不加 wrapper。
Bundle cask list 只给短名，第三方 cask 声明 tap，跳过安装时也须应用 tap 的 `trusted.casks`。
binman macOS GnuPG 的 locale/libiconv 构建缺陷导致 UTF-8/US-ASCII 启动警告，
可能错误编码非 ASCII 文件名；secret 原始字节不变。由上游 artifact 修复，应用不
过滤 stderr；更新后重跑 `task csecret:test`。

## Validation

[bats tests](tests/) 隔离 HOME 检查操作/权限/SSH，不代替原生 macOS 验证；plist 用
`plutil -lint`，Swift 变化验证对应脚本。原生安装入口见
[check-macos](../../.github/workflows/check-macos.yaml)，先发布 helper 避免旧产物，CI 不装
GUI cask/改默认应用。隔离 HOME 验证须显式设置工具 PATH 并检查 binding；macOS-only
变化不构建 Workspace，共享输入按根索引联动，不为文档检查执行安装。
AI 检查同时验证共享正文、引用完整性及未受管目录保留；历史重写 helper 的 smoke test
需 GNU `date`，原生完整安装后使用 binman 提供的命令再次验证。
