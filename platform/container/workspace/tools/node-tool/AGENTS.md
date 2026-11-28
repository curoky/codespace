# node-tool

## Scope

为 image、Workspace 与 macOS 安装隔离 npm CLI；pnpm 拥有依赖解析、registry/store，
installer 只拥有安装布局、命令发现与 binding。入口与实现见
[main.go](main.go)/[install.go](install.go)，不管理 runtime、manager 或 package catalog。

## Contracts

- package 使用隔离 pnpm project，environment 按原始包名位于 `envs/<package>`，
  scoped package 保留 `@scope/name` 层级，不编码目录名。命令从安装结果的 `package.json#bin`
  发现。launcher 相对 tools root 定位，payload 可搬迁，但固定 Node.js binding 必须仍可用；
  CLI 与子进程不随项目环境切换 runtime。
- pnpm 从调用方 PATH 查找；lifecycle scripts 按 package 显式授权，不默认放行。
- package 或公开命令存在时失败，不支持 overwrite/upgrade/rollback/并发写入。
  executable 自包含，不依赖外部模板、Python/uv 或运行期 compiler；路径须 Shell quoting。

## Runtime I/O

- **Reads**：校验选定 Node/pnpm，读取安装后的 manifest/命令；package 可来自本地，
  pnpm 配置与环境保持原生行为。
- **Writes**：默认 `~/.local/opt/node/tools`，`--root` 可改目标；写 store、独立 environment
  和 launcher。同 root 临时 project 退出时尝试清理，cache 可保留；不修改 profile/runtime。
- **Network**：pnpm 按 registry 配置或 `--registry` 下载 package/依赖；授权的 lifecycle
  scripts 以调用方权限执行，其网络/文件副作用不限制在 installer root。
- **Results & Failure**：输出安装 package/version/命令；准备失败不覆盖已有安装，但
  environment 发布后 launcher 失败可留下不完整安装，不自动回滚。

## Validation

[install_test.go](install_test.go) 检查冲突、binding 与搬迁。安装逻辑/binding/依赖行为变化
验证预装产物和运行期 helper；跨平台能力覆盖 macOS，仅 image 输入变化验证所属 image。
Workspace 装配变化构建最终主 image，`stage_node` 不覆盖最终 rootfs/权限，不能替代；
非行为修改使用根文档检查，不一律构建完整 image 或运行原生安装。
