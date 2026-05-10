# Codespace Repository Rules

## 目标与词汇

Codespace 在一个 monorepo 中提供可复现的个人开发 Workspace、Host 常驻 Service、
主机初始化和用户配置。声明式操作必须幂等，输入无效时 fail-fast。

- **Project**：Workspace 的配置蓝图。
- **Workspace**：Project 在 Host 上的持久副本及运行容器。
- **Service**：Host 上的单例常驻容器。
- **Host**：通过 SSH 访问并提供 rootful Podman 的节点。

只使用以上领域名称。

## Ownership

| 路径 | 职责 |
| --- | --- |
| `src/codespace/`、`tests/` | 控制面及其行为测试 |
| `platform/container/` | OCI image |
| `platform/{linux,macos,wsl}/` | Host 与 WSL 平台入口 |
| `dotfiles/` | Host 配置与复用片段 |
| `scripts/` | 仓库维护和启动脚本 |
| `.github/workflows/` | CI 与发布 |

## 不变量

- 产品、distribution、CLI、container prefix 与 registry repository 使用小写
  `codespace`；开发用户固定为 `x`（`5230:5230`）。
- 控制面只读取 `~/.config/codespace/config.yaml`；Host 数据只写入
  `~/codespace/{workspaces,services}/`。
- Workspace 与 Service inventory 使用不同的 `codespace.kind`。
- provider token 不进入容器；deploy private key 不离开容器；Agent 只通过 SSH
  转发的 UDS 暴露。
- Workspace sshd 与 Service 端口默认只绑定 Host loopback。
- Web UI 使用原生静态资源，不引入 Node.js 构建链。
- 不保留旧 schema、路径、label、tag、route、alias 或 fallback。

## 协作

代码、manifest 与 Taskfile 是实现细节的 source of truth；`AGENTS.md` 只记录边界和
不变量，复杂流程放同目录 `DESIGN.md`。不要在文档中复制 API、环境变量、版本或文件
清单。

使用 `task --list` 查看入口，提交前运行 `task check`。目录按领域组织，不增加无明确
ownership 的 `common`、`utils` 或 compatibility package；不要修改无关的用户或远端状态。
