# macOS Platform

## Scope

维护当前用户的 Homebrew、开发工具、macOS-specific home source、LaunchAgent、默认应用
与 client SSH wiring。维护 Skill 根据 actual state 选择独立操作，不使用统一 installer，
不创建 Podman machine 或构建 Workspace image；本地 Podman 只属于用户显式操作。

## Contracts

- [maintenance](maintenance/) 每个脚本独立完成一个可重复操作，不 source/call 同目录其他
  脚本，不扫描未声明路径；依赖缺失直接失败，顺序由 manage-macos-environment Skill 拥有。
- [Brewfile](Brewfile) 拥有完整 Homebrew state，[binman.yaml](binman.yaml) 拥有 standalone
  tools；runtime 与语言 CLI 独立维护，优先用 package manager 原生能力，否则重建受管目录。
  版本、工具清单和安装参数以声明/脚本为准。
- 默认 runtime、CLI binding、profile 与 editor 路径一致；可移植 Node/Python CLI 与
  Workspace 对齐。切换 Shell PATH 不改变已安装 CLI binding，变更后重装对应 CLI。
- Node/Java helper 来自本仓库 GHCR 的 macOS arm64 artifact，经 ORAS 获取，不要求本地
  compiler 或容器引擎；Java helper 本身不安装 distribution，也不要求预装 JDK。
- Temurin 提取 `Contents/Home`，采用 Linux runtime 根布局，不注册系统 JDK；Go/LLVM
  保留精确版本目录和 minor/major 相对链接，复用时仍维护入口。
- uv 使用原生默认选项提供 python/python3，隔离 CLI 显式绑定同一 interpreter；不改 uv
  metadata，cache 与项目 virtualenv 保持原生位置。rustup/SDK 根独立于运行期 CARGO_HOME，
  用户 `~/.cargo` 保留 CLI/cache；Rust SDK 精确锁定并校验，不用浮动 channel。
- macOS-specific source 位于 [rootfs/Users/x](rootfs/Users/x/)，共享 dotfile/SSH material
  由 [home-links.sh](maintenance/home-links.sh) 链接 Workspace source。默认 source 文件
  权限为 `0600`，可执行内容显式 `0755`；仅需独立 inode、权限或运行期修改时 copy。
- macOS 与容器 AI 规则保持一致结构，使用约定变化同步对应规则，不额外安装软件管理 Skill。
  静态 SSH config/key/known_hosts 来自声明 source；动态 Workspace route 属于控制面，
  home links 只准备目录与 include，不能覆盖动态 route。
- LaunchAgent 由对应脚本 copy/reload，不隐式启用可选 service；项目工具链覆盖在 Shell
  加载后设置。GNU GCC 由 Homebrew 管理，无后缀命令链接到用户 bin，不替换 Apple compiler。

## Main Flows

先根据 manifest 与 actual state 选择维护操作并核对依赖，再运行对应脚本；SDK archive
校验并准备后发布，语言 CLI 按所属 manager 安装或重建，home wiring 装配声明 source。
[atuin-daemon.sh](maintenance/atuin-daemon.sh) 与
[default-apps.sh](maintenance/default-apps.sh) 是独立的用户配置变更，不作为工具安装的隐式步骤。

## Runtime I/O

- **Reads**：读取 Brewfile、binman 声明、脚本锁定参数、macOS/shared rootfs 和当前已安装
  状态；home source 从仓库路径解析，写入目标从当前 `$HOME` 派生。
- **Writes**：Homebrew 维护 `/opt/homebrew` 与所声明应用；standalone tools 写 `~/.local`，
  SDK/helper/隔离 CLI 写 `~/.local/opt`，cache/manager metadata 保持原生布局。Node tools
  重建前删除旧 tools root，自管 runtime 替换受管版本目录，不承诺保留其中用户改动。
- **Home Changes**：home-links 对声明目标执行删除后 link/copy，可递归删除已有目录；
  同时调整 source 文件权限、准备私有 SSH 目录，并清理脚本声明的旧软件管理 skill 目录。
  完整替换范围以 [home-links.sh](maintenance/home-links.sh) 为准，不扩展到无关 home 路径。
- **Network**：Homebrew/binman 从声明的上游获取软件，bootstrap 使用 GitHub raw source；
  SDK 使用 GitHub Releases、`nodejs.org`、`go.dev` 与 `sh.rustup.rs` 等官方来源，helper
  从 `ghcr.io/curoky/codespace` 获取，Python/Node CLI 经原生 manager 的 PyPI/npm registry
  查询和下载。完整目标以脚本/manifest 为准，不上传用户业务文件。
- **System Changes**：[homebrew.sh](maintenance/homebrew.sh) 执行 force-cleanup，删除
  manifest 外 formula/cask 并清理 cache；bootstrap 或应用安装可能需要系统授权。
  Atuin 操作替换 `~/Library/LaunchAgents` 中声明 plist 并 reload 当前用户 service；
  默认应用操作执行 [Swift setup](scripts/set-default-apps.swift)，改变用户应用关联。
- **Results & Failure**：各脚本独立报告结果，不提供整套维护事务或自动 rollback。archive
  准备失败保留已有安装，发布阶段或 manager/home 配置失败可留下部分新状态；临时下载、
  staging 的清理范围以对应脚本为准。不要把成功下载或 link 当作 runtime/service 已可用。

## Pitfalls

- LLVM 最新官方 release 缺少 macOS arm64 artifact 时保留锁定版本，不换来源或自行构建。
- Snipaste tilde 展开缺少官方说明或原生验证，`last_save_folder` 保留绝对路径；launchd
  不展开变量，plist 路径也保留绝对值，不用 Shell wrapper 隐藏限制。
- Homebrew Bundle cask list 只给短名，第三方 cask 必须声明 tap；信任放 tap 的
  `trusted.casks`，即使跳过 cask 安装仍须应用信任声明。

## Validation

[bats tests](tests/) 在隔离 HOME 验证操作、权限与 SSH 结构，不替代原生 macOS 验证。
plist 变化用 `plutil -lint`，Swift setup 变化验证对应 script；macOS-only 变化不构建
Workspace，共享 source/artifact 变化按根索引联动。

[check-macos workflow](../../.github/workflows/check-macos.yaml) 在 Apple Silicon 原生检查，
push 先发布 helper，再由成功事件触发空用户目录安装验证，避免取到旧产物；PR 只做
contract 检查，不从 registry 安装工具。CI 不安装 GUI cask 或修改默认应用；真实维护
使用 manage-macos-environment Skill，不为文档验证执行安装。

Actions step 环境独立，切换 HOME 后显式将该用户安装期依赖加入 PATH；launcher 验证
通过项目 runtime PATH 检查固定 binding，不能靠先前 step 的环境证明可用。
