# Codespace

Codespace 是个人开发环境的声明式控制面。macOS 是唯一 client，Linux 是唯一受管 remote
Host；控制面通过本机 OpenSSH 管理 Host 上的 rootful Podman。

## System Boundaries

- **Project** 是 Workspace 的配置蓝图。
- **Workspace** 是 Project 在指定 Host 上的命名实例，拥有持久数据、SSH 入口和可选
  repository checkout。
- **Service** 是 Host 级单例，由配置声明 image、placement 和 container inputs。
- **WSL** 从 Workspace filesystem 派生本地 distribution，不属于控制面管理的 Host。
- 配置表达 desired state；Podman labels 与 inspect 数据表达 actual state。控制面不使用当前
  配置补齐已部署资源缺失的 metadata，也不自动迁移过时资源。
- 控制面依赖方向是 `web -> control -> workspaces/services -> runtime`。Web 不拥有业务状态，
  runtime 不读取应用配置，container artifact 不包含控制面逻辑。

## Context Index

按任务只加载相关上下文；目录内的 `AGENTS.md` 继承本文件，且比本文件更接近实现。

| 任务 | 先读 | 需要联动时再读 |
| --- | --- | --- |
| 控制面配置、Web、Workspace、Runtime、Maintenance 或 CLI | `src/codespace/AGENTS.md` | 修改容器端 Agent 协议时同时读 `platform/container/workspace/agent/AGENTS.md` |
| Workspace image、resource payload、rootfs 或 s6 graph | `platform/container/workspace/AGENTS.md` | 内嵌 Agent 或 tool 的下层文档 |
| Service image | `platform/container/services/AGENTS.md` | 修改共享 s6 资产时同时读 Workspace 文档 |
| Framework image | `platform/container/frameworks/AGENTS.md` | 对应 combo 的 Dockerfile 与 build script |
| macOS 安装器、dotfiles 或 client SSH | `platform/macos/AGENTS.md` | 共享 home 变更同时读 Workspace 文档 |
| WSL build、boot 或 Windows wiring | `platform/wsl/AGENTS.md` | 继承的 Workspace s6 变更同时读 Workspace 文档 |

`platform/container/workspace/USAGE.md` 是安装进 Workspace、供其中 Agent 使用的全局使用
文档；维护仓库本身时以各级 `AGENTS.md` 为准。

## Repository Rules

- 跨模块边界和上下文索引只写入根 `AGENTS.md`；模块维护上下文写入最接近实现的
  `AGENTS.md`。不新增 `DESIGN.md` 或 `README.md`。
- 配置 schema、container manifest、代码、测试与 `Taskfile.yaml` 是可变实现细节的
  source of truth。行为改变时同步更新受影响的 `AGENTS.md`，不要在文档中复制易失效的
  版本、端口或完整清单。
- 注释只解释代码无法表达的约束或外部兼容性原因，不复述实现。
- 目录按领域组织，不增加无明确 ownership 的 `common`、`utils` 或 compatibility
  package；不保留旧路径、fallback 或迁移层。
- 不修改无关的用户、工作树或远端状态；真实 token、secret 与机器配置不得提交。

## Validation

- 文档或非行为变更至少运行 `task check`。
- 控制面、脚本或其他行为变更运行 `task check:full`。
- OCI、macOS 或 WSL artifact 变更还要执行目标目录 `AGENTS.md` 指定的 build、export 或
  平台验证；`task check:full` 不替代 artifact 构建。
