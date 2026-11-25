# node-tool

## Scope

为 image 构建、Workspace 与 macOS maintenance 单向安装隔离 npm CLI。pnpm 拥有依赖解析、
registry 与 store；installer 只拥有安装布局、命令发现与 runtime binding，不管理 Node.js、
pnpm 或 package catalog，也不提供 init、upgrade、rollback 或并发写入能力。

## Contracts

- 每个 package 使用隔离 pnpm project；命令从安装结果的 `package.json#bin` 发现，不维护
  package-to-command 清单。launcher 相对 tools root 定位，安装结果可跨 stage 搬迁，但固定
  Node.js binding 仍须可用，CLI 及其子进程不随项目环境切换 runtime。
- 默认 root 从当前用户 Home 派生，构建 stage 显式设置固定用户 HOME；runtime 覆盖只在
  确有需要时传递，pnpm 从调用方 PATH 查找。
- lifecycle scripts 必须由调用方按 package 显式授权，不默认放行。package 或公开命令
  已存在时失败，不覆盖；这不是可重复安装接口。
- 独立 Go executable 无运行期 Python、uv 或 compiler 依赖；
  [launcher template](launcher.bash.tmpl) 经 `go:embed` 编译并用 `text/template` 渲染，
  路径使用 Shell quoting，不依赖外部模板文件。

## Main Flows

[installTool](install.go) 校验 Node/pnpm，在 root 内创建临时 project 并调用 pnpm，读取
安装后的 manifest 发现命令、检查冲突，再发布 environment 和 launcher。细节与可选参数
以 [main.go](main.go) 和 [install.go](install.go) 为准，不自行实现 registry 或依赖解析。

## Runtime I/O

- **Reads**：读取选定 runtime、pnpm executable、安装后 manifest 与命令目标；package
  参数可指向本地来源，pnpm 仍遵循自身配置和环境。
- **Writes**：默认写入 `~/.local/opt/node/tools`，`--root` 可改变目标；包括持久 store、
  package environments 和 `bin` launcher。临时 project 位于同 root，退出时尝试清理。
- **Network**：pnpm 按 registry 配置或 `--registry` 解析、下载 package 与依赖。授权的
  lifecycle scripts 以调用方权限运行，其网络与文件副作用不局限于 installer root。
- **Results & Failure**：成功输出 package/version 与命令。准备失败不覆盖已有安装，但
  cache 可保留；environment 发布后 launcher 写入失败可能留下不完整安装，不自动回滚。
  installer 本身不修改 Shell profile 或系统 runtime。

## Validation

[install_test.go](install_test.go) 验证安装、命令冲突、binding 与搬迁。installer、依赖、
预装 package、binding 或 profile 变化按 Workspace 约定构建完整主 image，覆盖预装产物、
运行期 helper 与 macOS；开发可先构建 Dockerfile 的 `stage_node`，但它不覆盖最终 rootfs、
权限和运行期 helper，不能替代完整 image 验证。
