# Codespace

Codespace 在 monorepo 中维护个人开发 Workspace、Host 常驻 Service 及 Host 配置。
声明式操作必须幂等，输入无效时 fail-fast。

## 领域模型

- **Project**：Workspace 配置蓝图。
- **Workspace**：Project 在 Host 上的持久副本及运行容器。
- **Service**：Host 上的单例常驻容器。
- **Host**：通过 SSH 访问并提供 rootful Podman 的节点。

## Ownership

| 路径 | 职责 |
| --- | --- |
| `src/codespace/`、`tests/` | 控制面及其行为测试 |
| `platform/container/` | OCI image |
| `platform/macos/` | macOS Host 配置 |
| `platform/wsl/` | WSL rootfs 与 Windows 辅助资产 |
| `scripts/` | 仓库维护与启动入口 |
| `.github/workflows/` | CI 与发布 |

## 约束

- control plane client 只支持 `platform/macos/` 管理的 `/Users/x` macOS；Workspace
  runtime 只支持 `platform/container/workspace/` contract。
- 产品、distribution、CLI、container prefix 与 registry repository 使用小写
  `codespace`；开发用户固定为 `x`（`5230:5230`）。
- 控制面只读取 `~/.config/codespace/config.yaml`；其管理的 Host 数据只写入
  `~/codespace/{workspaces,services}/`。
- Workspace 与 Service inventory 使用不同的 `codespace.kind`。
- provider token 不进入容器；deploy private key 不离开容器；Agent 只通过 SSH
  转发的 UDS 暴露。
- Host-facing listener 默认只绑定 loopback；bridge gateway 或 LAN 暴露必须显式。
- Web UI 使用原生静态资源，不引入 Node.js 构建链。
- 不保留旧 schema、路径、label、tag、route、alias 或 fallback。

## 文档与协作

- 代码、manifest 与 Taskfile 是实现的 source of truth。
- `AGENTS.md` 只记录所在目录的 ownership、非显然约束与导航；不重复父级规则，
  不枚举可从 source 直接读出的版本、参数、文件或当前目录数量。
- 跨文件流程与设计理由放同目录 `DESIGN.md`，API contract 留在代码和测试中。
- 注释只解释当前实现中无法直接读出的意图，不记录演化历史。
- 目录按领域组织，不增加无明确 ownership 的 `common`、`utils` 或 compatibility
  package。

使用 `task --list` 查看入口，提交前运行 `task check`。不修改无关的用户或远端状态。
