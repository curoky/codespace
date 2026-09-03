# Codespace Repository Rules

## 领域

Codespace 在一个 monorepo 中提供可复现的个人开发 Workspace、Host 常驻 Service、
主机初始化和用户配置。声明式操作必须幂等，输入无效时 fail-fast。

- **Project**：Workspace 的配置蓝图。
- **Workspace**：Project 在 Host 上的持久副本及运行容器。
- **Service**：Host 上的单例常驻容器。
- **Host**：通过 SSH 访问并提供 rootful Podman 的节点。

领域对象只使用以上名称。

## Ownership

| 路径 | 职责 |
| --- | --- |
| `src/codespace/`、`tests/` | 控制面及其行为测试 |
| `platform/container/` | OCI image |
| `platform/macos/` | macOS Host 配置 |
| `platform/wsl/` | WSL rootfs 与 Windows 辅助资产 |
| `scripts/` | 仓库维护和启动脚本 |
| `.github/workflows/` | CI 与发布 |

## 全局约束

- 产品、distribution、CLI、container prefix 与 registry repository 使用小写
  `codespace`；开发用户固定为 `x`（`5230:5230`）。
- 控制面只读取 `~/.config/codespace/config.yaml`；其管理的 Host 数据只写入
  `~/codespace/{workspaces,services}/`。
- Workspace 与 Service inventory 使用不同的 `codespace.kind`。
- provider token 不进入容器；deploy private key 不离开容器；Agent 只通过 SSH
  转发的 UDS 暴露。
- Workspace sshd 与 Service 端口默认只暴露到 Host loopback。
- Web UI 使用原生静态资源，不引入 Node.js 构建链。
- 不保留旧 schema、路径、label、tag、route、alias 或 fallback。

## 协作

代码、manifest 与 Taskfile 是实现的 source of truth；`AGENTS.md` 只记录边界和约束，
复杂流程放同目录 `DESIGN.md`，不要复制 API、环境变量、版本或文件清单。

代码注释只解释当前实现中无法直接读出的意图与约束，不记录演化历史。跨文件导航集中
放在 `AGENTS.md`，由它单向索引同目录专题文档。

使用 `task --list` 查看入口，提交前运行 `task check`。目录按领域组织，不增加无明确
ownership 的 `common`、`utils` 或 compatibility package，不修改无关的用户或远端状态。
