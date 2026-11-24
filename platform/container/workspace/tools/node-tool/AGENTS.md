# node-tool

为主 image 构建、Workspace 运行期和 macOS maintenance 提供单向 npm CLI 安装。每个 package
使用隔离的 pnpm project；依赖解析、registry 与 store 交给 pnpm，installer 不管理 Node.js、
pnpm 或 package catalog。

## Contracts

- 调用方显式选择 Node.js runtime，CLI 及其子进程固定使用该 runtime，不受项目环境切换影响。
- 从安装结果的 `package.json#bin` 发现命令，不维护 package-to-command 清单；launcher
  相对 tools root 定位，使安装结果可在 image stage 间搬迁，但绑定的 Node.js 路径仍须可用。
- 默认 tools root 从当前用户的 Home 派生；构建 stage 显式指定安装根。
- lifecycle scripts 必须由调用方按 package 显式授权，不默认放行。
- 目标或公开命令已存在时失败，不扩展 overwrite、upgrade、rollback 或并发写入能力。
- installer 使用本目录独立的 uv project，与调用方 virtualenv 隔离；仅显式 `init` 同步
  环境，普通调用不安装依赖。`init` 使用调用方 PATH 中的 uv 与原生 Python 安装目录配置。
  修改依赖后必须重新 `init`。

## Validation

通用检查遵循根文档。修改 installer、依赖、预装 package、runtime binding 或 profile 后，
按上层约定构建完整主 image，同时覆盖预装产物与运行期 helper。开发时可先构建 CLI stage：

```bash
/opt/podman/bin/podman build . --network=host \
  --file platform/container/workspace/Dockerfile \
  --target stage_node \
  --tag codespace-node-tool-test
```

CLI stage 不覆盖最终 rootfs、权限与 installer 环境，不能替代完整主 image 验证。
