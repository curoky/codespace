# Codespace Repository Rules

## 目标

Codespace 在一个 monorepo 中提供可复现的个人开发 Workspace、Host 常驻 Service、主机初始化和用户配置。
所有声明式操作必须幂等并在输入无效时 fail-fast。

## Core Concepts

- **Project**：声明 source、Workspace image、目标 Host 与容器参数的配置蓝图。
- **Workspace**：某 Project 在某 Host 上的持久工作副本及其运行容器。
- **Service**：某 Host 上的单例常驻容器。
- **Host**：通过 SSH 访问并提供 rootful Podman 的执行节点。

代码、配置、API、UI 与文档统一使用这些名称，不引入平行领域概念。

## Ownership

| 路径 | 职责 |
| --- | --- |
| `src/codespace/` | 本地控制面、API、Web UI 与维护命令 |
| `tests/` | 控制面对外行为测试，目录与 package ownership 对齐 |
| `platform/container/` | Workspace、Service、framework image 与 Workspace home 配置 |
| `platform/linux/` | Linux host 安装入口 |
| `platform/macos/` | macOS host 安装、LaunchAgent 与主机脚本 |
| `platform/wsl/` | WSL image、boot 与 export |
| `dotfiles/` | 按工具组织的 Host 用户配置与可复用配置片段 |
| `scripts/` | 仓库维护、hook 与控制面启动脚本 |
| `.github/workflows/` | 检查、镜像发布与 registry 清理 |

具体实现约束下沉到最近的 `AGENTS.md`；复杂流程放同目录 `DESIGN.md`。修改契约时同步更新拥有它的文档，
根文档不复制 leaf 细节。

## Global Contracts

- 产品、Python distribution、CLI、container prefix 与 registry repository 统一为小写 `codespace`。
- 开发用户固定为 `x`，uid/gid `5230:5230`。
- 唯一控制面配置为 `~/.config/codespace/config.yaml`；仓库只提交 `config.example.yaml`。
- Host 数据只写入 `~/codespace/workspaces/` 与 `~/codespace/services/`。
- Workspace 与 Service inventory 必须使用不相交的 `codespace.kind` label。
- provider token 不进入容器；deploy private key 不离开容器；Agent 只通过 SSH 转发的 UDS 暴露。
- Workspace sshd 和 Service 端口只绑定 Host loopback，除非 leaf contract 明确要求其他边界。
- Web UI 使用原生静态资源，不引入 Node.js 构建链。
- 不保留旧 schema、路径、label、tag、route、兼容 alias 或 fallback。
- 说明与约束文档使用中文；代码标识、命令、协议与外部 API 保留英文。

## Commands

```bash
task sync
task serve
task check
```

构建和维护入口以 `task --list` 为准。清理与 secret 同步默认 dry-run，只有显式 `--apply` 才修改远端状态。

## Change Rules

- 目录与模块按领域 ownership 组织，不增加无明确边界的 `common`、`utils` 或 compatibility package。
- 配置在入口集中校验；代码不散落读取裸环境变量。
- Shell 只负责流程编排，复杂数据与业务逻辑放 Python。
- 优先添加针对受影响行为的聚焦测试；提交前运行 `task check`。
- 不修改与当前任务无关的用户文件、Host 数据、远端 container、Podman secret 或 image。
