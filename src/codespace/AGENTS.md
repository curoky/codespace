# Codespace Control Plane 约束

`src/codespace/` 是仅监听本机的单进程控制面。它读取
`~/.config/codespace/config.yaml`，通过 system OpenSSH 连接提供 rootful Podman 的 Host，并提供原生
Web UI。当前架构与数据流见 [`DESIGN.md`](DESIGN.md)。

## 领域与模块

| 路径 | 职责 |
| --- | --- |
| `config.py` | 单文件 YAML schema、校验及 Project/Service placement resolution |
| `control.py` | Config、连接池、token store、两个 manager 与 Dashboard 聚合 |
| `operations.py` | Workspace/Service 共用的进程内 operation model 与 store |
| `runtime/` | canonical `ContainerSpec`、Podman/SSH transport、Host 路径和命令原语 |
| `workspaces/` | Workspace identity、inventory、create/delete/logs、Agent、provider 与 SSH 投影 |
| `services/` | Service identity、inventory、apply/remove/logs |
| `web/` | FastAPI boundary、Dashboard read model 与原生静态 UI |
| `maintenance/` | dry-run-first secret、Workspace 数据和 deploy key 收敛命令 |

依赖方向固定为 `web -> control -> workspaces/services -> runtime`。`config.py` 可依赖领域 spec 与
`ContainerSpec`；`runtime/` 不得依赖 Web、manager 或 Config。Workspace 与 Service 不互相调用。

## 运行与验证

```bash
uv sync --locked
uv run codespace serve
uv run codespace secrets sync
uv run codespace workspaces prune
uv run codespace deploy-keys prune

uv run ruff format --check src/codespace tests
uv run ruff check src/codespace tests
uv run mypy src/codespace
uv run pytest
```

维护命令默认只展示完整计划；只有 `--apply` 才执行写操作。

## Configuration

- 只读取 `~/.config/codespace/config.yaml`，不读取仓库配置、扩展文件或多层 merge。
- 顶层字段固定为 `hosts`、`project_defaults`、`projects`、`services`、`tokens`、`secrets`。
- `source` 是 `github`、`gitlab`、`git`、`empty` discriminated union。
- Project 按 `project_defaults -> project -> placement` 解析；Service 按 `service -> placement`
  解析。每个字段整体覆盖，不深合并 list 或 mapping。
- `volumes`、`secrets`、`ulimits`、`ports` 只接受具名 mapping。
- Project/Workspace/Service ID 及 Host alias 必须通过 Pydantic pattern 校验；未知字段 fail-fast。
- token 与 secret value 不得出现在 API、日志或 model repr。

## Runtime Contracts

- Workspace identity：`codespace-workspace-<host>-<project>-<workspace>`。
- Service identity：`codespace-service-<service>`。
- Workspace label：`codespace.kind=workspace`，以及 `project`、`workspace`、`source`、`image`、
  `platform`、`ssh-port`；source 按需增加 `repository` 或 `git-url`。
- Service label：`codespace.kind=service`，以及 `service`、`image`。
- Host 数据：
  - `~/codespace/workspaces/<project>/<workspace>/{workspace,upload,cache,control}`
  - `~/codespace/services/<service>`
- Workspace Agent env 固定为 `CODESPACE_SOURCE_TYPE`、`CODESPACE_CLONE_URL`、
  `CODESPACE_CHECKOUT_PATH`、`CODESPACE_OPEN_PATH`。
- Workspace 加密使用 Podman secret `codespace_workspace_key`，注入
  `CODESPACE_WORKSPACE_KEY`；`/upload` 与 `/cache` 始终明文。
- Service data volume 只允许 `${SERVICE_DATA}` 占位符。

## HTTP 与 CLI

Web 生命周期 API 固定为：

- `GET /api/dashboard`
- `PUT /api/providers/{provider}/token`
- `POST /api/projects/{project}/workspaces`
- `GET /api/projects/{project}/hosts/{host}/workspaces/{workspace}/logs`
- `DELETE /api/projects/{project}/hosts/{host}/workspaces/{workspace}`
- `DELETE /api/projects/{project}/hosts/{host}/operations/{workspace}`
- `POST /api/services/{service}/hosts/{host}/apply`
- `GET /api/services/{service}/hosts/{host}/logs`
- `DELETE /api/services/{service}/hosts/{host}`
- `DELETE /api/services/{service}/hosts/{host}/operation`

CLI 只提供 `serve` 与三个维护入口，不增加 Workspace/Service 生命周期命令。应用固定单 worker，监听
`127.0.0.1:8003`；错误响应固定为 `{"error": "..."}`。UI 只在存在 `queued` 或 `running`
operation 时轮询。

## 安全边界

- Rootful Podman socket 等价于 Host root 权限；SSH host key verification 不得关闭。
- provider token 仅存在于配置读取结果或进程内存，不得返回、记录或写回。
- deploy private key 只在对应 Workspace 容器内存在；控制面只接收 public key。
- Agent 仅监听逐 Workspace `control/agent.sock`，经 OpenSSH StreamLocal 转发，不发布 TCP。
- Project 用户 volume/secret 不得覆盖受管 mount 或保留 env。
- HTTPS provider 使用系统 CA；不得关闭 TLS verification。

## 变更规则

- 公开 schema、API、label、env、路径或生命周期变化必须同步修改 `DESIGN.md` 与聚焦测试。
- 不增加旧 schema、旧 route、旧 label、旧路径探测、alias、shim 或 migration。
- 生命周期失败保留现场并记录 failed operation，不做自动回滚。
- Web UI 保持原生 HTML/CSS/JS，不增加 Node.js 构建链。
