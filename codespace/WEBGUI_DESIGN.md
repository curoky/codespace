# Codespace Web GUI 设计

本文档描述 Codespace client 的本地 Web GUI 设计。Web GUI 是现有 CLI client 的可视化控制面，
用于通过一个 Dashboard 管理配置文件中的多个 agent，并在指定 agent 上创建 / 删除 codespace
容器。

> **文档边界**：底层 agent / 容器 / SSH key 注入 / GitHub deploy key 协议仍以
> [`DESIGN.md`](./DESIGN.md) 为准；本文只描述 Web GUI、client 侧配置、Dashboard 聚合和
> Web API 设计。

## 1. 目标与非目标

### 目标

- 启动本地 Web GUI，仅需要指定 Web 服务端口。
- 从单个 YAML 配置文件读取多个 agent profile。
- Dashboard 汇总展示所有 agent 的在线状态与现有 codespace 容器。
- 支持在指定 agent 上创建 codespace，并展示完整创建进度。
- 支持删除 codespace，可选择是否 purge workspace。
- GitHub token 始终保留在 client 本地，不发送给 agent。
- 复用现有 client 能力：login key、deploy key 注册 / 吊销、`~/.ssh/config` 管理、agent
  operation 轮询与回滚语义。

### 非目标（MVP）

- 不提供多用户登录、RBAC 或远程共享控制台能力。
- 不把 Web GUI 部署到 agent 侧。
- 不将 GitHub token 持久化到配置文件。
- 不提供浏览器内 terminal、容器日志、IDE deep link。
- 不持久化 Web operation 历史；server 重启后通过 agent list 重新发现实际容器状态。

## 2. 总体架构

```
Browser
  │ HTTP (localhost)
  ▼
Local Web GUI Server (client side)
  │ 读取 ~/.config/codespace/config.yaml
  │ 管理本地 ~/.ssh/codespace 与 ~/.ssh/config
  │ 使用本地 GitHub token 注册 / 吊销 deploy key
  ├──────────────▶ Agent home   ──▶ Podman containers
  ├──────────────▶ Agent office ──▶ Podman containers
  └──────────────▶ Agent lab    ──▶ Podman containers
```

Web GUI 运行在 client 本机，默认只监听 `127.0.0.1`。它直接访问配置中的多个 agent HTTP API，
并在本地完成 GitHub 与 SSH 配置相关操作。agent 仍保持无状态，不接触 GitHub token。

## 3. 启动方式

Web GUI 启动时只暴露端口参数：

```bash
uv run python -m codespace.client web --port 8765
```

默认监听：

```text
127.0.0.1:8765
```

实现上可以保留高级 `--host` 参数，但默认不应暴露到局域网。若用户显式监听 `0.0.0.0`，启动时
必须打印安全警告：Web GUI 可访问本地 GitHub token、SSH key 与 `~/.ssh/config`，不应暴露给
不可信网络。

## 4. YAML 配置文件

### 4.1 路径

默认配置文件：

```text
~/.config/codespace/config.yaml
```

可用环境变量覆盖：

```bash
CODESPACE_CONFIG=/path/to/config.yaml
```

优先级：

```text
CODESPACE_CONFIG > ~/.config/codespace/config.yaml
```

### 4.2 示例

```yaml
defaults:
  agent: home
  image: ghcr.io/curoky/devspace:codespace-image-debian12
  user: x
  workspace: default
  extra_repos:
    - curoky/ai-coding-config

github:
  token_env: GITHUB_TOKEN

agents:
  home:
    name: Home Server
    agent_url: http://10.0.0.5:8001
    ssh_host: 10.0.0.5

  office:
    name: Office Workstation
    agent_url: http://10.0.0.8:8001
    ssh_host: 10.0.0.8

  lab:
    name: Lab Machine
    agent_url: http://lab.example.com:8001
    ssh_host: lab.example.com
```

### 4.3 字段

#### `defaults`

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `agent` | 是 | 默认选中的 agent profile id |
| `image` | 是 | 创建 codespace 的默认开发镜像 |
| `user` | 否 | 容器登录用户，默认 `shared.DEFAULT_CONTAINER_USER` |
| `workspace` | 否 | 默认 workspace，默认 `shared.DEFAULT_WORKSPACE` |
| `extra_repos` | 否 | 默认额外只读 repo 列表 |

#### `github`

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `token_env` | 否 | GitHub token 所在环境变量名，默认 `GITHUB_TOKEN` |

不建议支持明文 `token` 字段。若未来为兼容性支持，也必须在 UI 和文档中标记为不推荐。

#### `agents.<id>`

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `name` | 否 | UI 展示名；不填则使用 agent id |
| `agent_url` | 是 | agent HTTP API 地址 |
| `ssh_host` | 是 | client SSH 连接该 agent 宿主机时使用的 host |

### 4.4 校验规则

- 配置文件必须是 YAML mapping。
- 至少配置一个 agent。
- `defaults.agent` 必须存在于 `agents`。
- agent id 必须匹配 `^[\w.-]+$`，因为它会参与默认 SSH alias 生成。
- `defaults.workspace` 必须匹配 `shared.WORKSPACE_RE`。
- `defaults.extra_repos` 每项必须匹配 `shared.REPO_RE`。
- 每个 `agent_url` 与 `ssh_host` 均不能为空。
- `github.token_env` 只保存环境变量名，API 只返回 `has_token`，不得返回 token 明文。

YAML 解析建议使用 `PyYAML` 的 `yaml.safe_load`，再交给 Pydantic model 校验。

## 5. 模块划分

建议新增：

```text
codespace/client/config.py       # 读取 / 校验 YAML 配置
codespace/client/service.py      # CLI 与 Web 共享的 client 编排逻辑
codespace/client/web.py          # 本地 FastAPI Web server
codespace/client/static/         # MVP 原生 HTML / JS / CSS
```

CLI 与 Web 不应复制 create / delete 编排逻辑，而应共享 `service.py`。目标依赖方向：

```text
Typer CLI ─┐
           ├── codespace.client.service ─── agent / github / ssh_config
FastAPI ───┘
```

## 6. Dashboard 能力

Dashboard 是 Web GUI 的核心页面，必须同时展示多个 agent 与其容器。

### 6.1 页面布局

```text
┌──────────────────────────────────────────────────────────────┐
│ Header                                                       │
│ Codespace Dashboard        Config: ~/.config/codespace/...   │
├──────────────────────────────────────────────────────────────┤
│ Agent Summary                                                │
│ [Home: Online] [Office: Offline] [Lab: Online]               │
├──────────────────────────────────────────────────────────────┤
│ Toolbar                                                      │
│ Agent: [All ▼]  Search: [repo/workspace/alias]  [Refresh]    │
│                                             [Create]         │
├──────────────────────────────────────────────────────────────┤
│ Codespace Table                                              │
│ Agent | Repo | Workspace | Alias | Status | SSH | Actions    │
├──────────────────────────────────────────────────────────────┤
│ Operation Panel / Drawer                                     │
│ Creating home-devspace-default: pulling image ...            │
└──────────────────────────────────────────────────────────────┘
```

### 6.2 Agent Summary

对配置文件里的每个 agent 展示：

| 字段 | 说明 |
| --- | --- |
| Agent ID / 名称 | `home` / `Home Server` |
| URL | `agent_url` |
| SSH Host | `ssh_host` |
| 状态 | `online` / `offline` |
| 容器数量 | 当前 agent 返回的 codespace 数量 |
| 错误信息 | 离线或请求失败时显示 |

在线状态通过短超时请求判断：

```http
GET <agent_url>/codespaces
```

任一 agent 离线不应阻塞整个 Dashboard；离线 agent 显示错误，其余 agent 正常展示。

### 6.3 Codespace Table

主表格展示所有 agent 的 codespace：

| 列 | 示例 | 说明 |
| --- | --- | --- |
| Agent | Home | 配置 profile |
| Repo | `curoky/devspace` | 容器 label |
| Workspace | `default` | 容器 label |
| Alias | `home-devspace-default` | 本地 SSH alias，可能为空 |
| Status | `running` | agent 返回的容器状态 |
| SSH Host | `10.0.0.5` | profile `ssh_host` |
| Port | `49207` | agent 返回的 `port` |
| SSH | `ssh home-devspace-default` | 可复制 |
| Actions | Delete / Purge | 删除操作 |

支持能力：

- 按 agent 过滤。
- 搜索 repo / workspace / alias。
- 手动刷新。
- 可选自动刷新，例如 10 秒一次。
- 复制 SSH 命令。

## 7. Alias 与 SSH 配置

多 agent 场景下默认 alias 必须包含 agent id，避免不同 agent 上相同 repo/workspace 冲突：

```text
<agent-id>-<repo-name>-<workspace>
```

示例：

```text
home-devspace-default
office-devspace-default
```

Web 创建流程写入 `~/.ssh/config` 时，应在 Host block 中保存 agent 元数据，便于 Dashboard
反查本地 alias：

```sshconfig
Host home-devspace-default
  HostName 10.0.0.5
  Port 49207
  User x
  IdentityFile ~/.ssh/codespace/home-devspace-default

  # codespace.id abc123
  # codespace.repo curoky/devspace
  # codespace.agent home
```

若 agent 上存在容器但本地没有 alias，Dashboard 仍应展示该容器，并提供 raw SSH 命令：

```text
ssh x@10.0.0.5 -p 49207
```

MVP 可只展示 raw SSH 命令；后续可增加 `Create Local SSH Alias` 操作。

## 8. 创建 codespace

点击 Dashboard 的 `Create` 打开 modal / drawer：

```text
Create Codespace

Agent        [Home Server ▼]
Repo         [curoky/devspace]
Workspace    [default]
Alias        [home-devspace-default]
Image        [ghcr.io/curoky/devspace:codespace-image-debian12]
User         [x]
Extra repos  [✓] curoky/ai-coding-config

[Cancel] [Create]
```

字段默认值：

| 字段 | 默认值来源 |
| --- | --- |
| Agent | `defaults.agent` |
| Repo | 空 |
| Workspace | `defaults.workspace` |
| Alias | `<agent-id>-<repo-name>-<workspace>` |
| Image | `defaults.image` |
| User | `defaults.user` |
| Extra repos | `defaults.extra_repos` |

当 agent / repo / workspace 改变且用户未手动编辑 alias 时，前端自动重新生成 alias。

## 9. 创建流程与进度

Web GUI 需要维护一层 client-side operation，因为完整创建流程横跨 agent 和本地 client 操作。

```text
Browser POST /api/agents/{agent_id}/codespaces
  ↓
Web server 创建 WebOperation
  ↓ 后台线程
preparing login key
requesting agent creation
agent: queued
agent: checking workspace
agent: preparing workspace directory
agent: pulling image ...
agent: creating container
agent: injecting credentials
agent: ready
registering deploy key: main repo
registering deploy key: extra repos
writing ssh config
ready
```

### 9.1 回滚语义

- agent 创建失败：删除本地 login key。
- agent 创建成功但 deploy key 注册失败：吊销已注册的 deploy key，删除远端容器，删除本地 login key。
- 写 `~/.ssh/config` 失败：吊销 deploy key，删除远端容器，删除本地 login key。
- 删除远端容器失败时仍保留错误给用户；不静默吞掉主错误。

## 10. 删除 codespace

Dashboard 每行提供：

```text
[Delete] [Delete + Purge]
```

删除流程：

1. 根据 `agent_id` 找到 agent profile。
2. 根据本地 alias / codespace id 解析本地已知 repos。
3. 使用本地 GitHub token 吊销 deploy key。
4. 调用 agent：`DELETE /codespaces/{id}`，需要 purge 时带 `?purge=true`。
5. 删除本地 ssh config Host block。
6. 删除本地 login keypair。

如果本地没有 alias，仍可删除 agent 上的容器；此时 main repo 可从 agent 返回的 `repo` 字段得知，
但 extra repos 可能无法完整吊销，应在 UI 中显示 warning。

## 11. Web API

Web API 仅服务本地浏览器，不是远程公共 API。

### 11.1 `GET /api/config`

返回配置摘要，不包含 token 明文：

```json
{
  "default_agent": "home",
  "defaults": {
    "image": "ghcr.io/curoky/devspace:codespace-image-debian12",
    "user": "x",
    "workspace": "default",
    "extra_repos": ["curoky/ai-coding-config"]
  },
  "github": {
    "token_env": "GITHUB_TOKEN",
    "has_token": true
  },
  "agents": [
    {
      "id": "home",
      "name": "Home Server",
      "agent_url": "http://10.0.0.5:8001",
      "ssh_host": "10.0.0.5"
    }
  ]
}
```

### 11.2 `GET /api/dashboard`

聚合所有 agent 状态、codespaces 与当前 Web operations：

```json
{
  "agents": [
    {
      "id": "home",
      "name": "Home Server",
      "agent_url": "http://10.0.0.5:8001",
      "ssh_host": "10.0.0.5",
      "status": "online",
      "error": null,
      "codespace_count": 2
    }
  ],
  "codespaces": [
    {
      "agent_id": "home",
      "agent_name": "Home Server",
      "id": "abc123",
      "repo": "curoky/devspace",
      "workspace": "default",
      "alias": "home-devspace-default",
      "ssh_host": "10.0.0.5",
      "port": 49207,
      "user": "x",
      "status": "running",
      "ssh_command": "ssh home-devspace-default",
      "raw_ssh_command": "ssh x@10.0.0.5 -p 49207",
      "has_local_alias": true
    }
  ],
  "operations": []
}
```

### 11.3 `POST /api/agents/{agent_id}/codespaces`

请求：

```json
{
  "repo": "curoky/devspace",
  "workspace": "default",
  "alias": "home-devspace-default",
  "image": "ghcr.io/curoky/devspace:codespace-image-debian12",
  "user": "x",
  "extra_repos": ["curoky/ai-coding-config"]
}
```

返回：

```json
{
  "operation_id": "web-op-123"
}
```

### 11.4 `GET /api/operations/{operation_id}`

返回：

```json
{
  "id": "web-op-123",
  "agent_id": "home",
  "alias": "home-devspace-default",
  "repo": "curoky/devspace",
  "workspace": "default",
  "status": "running",
  "stage": "agent: creating container",
  "error": null,
  "codespace": null
}
```

### 11.5 `DELETE /api/agents/{agent_id}/codespaces/{codespace_id}`

参数：

```text
purge=false | true
```

返回：

```json
{
  "ok": true,
  "workspace_removed": false
}
```

## 12. 后端数据模型

建议模型：

```python
class AgentProfile(BaseModel):
    id: str
    name: str
    agent_url: str
    ssh_host: str

class DefaultsConfig(BaseModel):
    agent: str
    image: str
    user: str = shared.DEFAULT_CONTAINER_USER
    workspace: str = shared.DEFAULT_WORKSPACE
    extra_repos: list[str] = Field(default_factory=list)

class GithubConfig(BaseModel):
    token_env: str = "GITHUB_TOKEN"

class WebConfig(BaseModel):
    defaults: DefaultsConfig
    github: GithubConfig = Field(default_factory=GithubConfig)
    agents: dict[str, AgentProfile]
```

Dashboard：

```python
class AgentStatus(BaseModel):
    id: str
    name: str
    agent_url: str
    ssh_host: str
    status: Literal["online", "offline"]
    error: str | None = None
    codespace_count: int = 0

class DashboardCodespace(BaseModel):
    agent_id: str
    agent_name: str
    id: str
    repo: str
    workspace: str
    alias: str | None
    ssh_host: str
    port: int
    user: str
    status: str | None
    ssh_command: str
    raw_ssh_command: str
    has_local_alias: bool

class WebOperation(BaseModel):
    id: str
    agent_id: str
    alias: str
    repo: str
    workspace: str
    status: Literal["queued", "running", "succeeded", "failed"]
    stage: str
    agent_operation_id: str | None = None
    codespace: shared.Codespace | None = None
    error: str | None = None
```

## 13. 并发与超时

- Dashboard 加载时并发请求所有 agent。
- 每个 agent 请求使用短超时，例如 2–5 秒。
- 单个 agent 失败不影响整体 Dashboard。
- Web operations 存在本进程内存中，用 `Lock` 保护并发读写。
- 创建操作使用后台线程执行，Web API 快速返回 operation id。

## 14. 安全设计

- 默认仅监听 `127.0.0.1`。
- GitHub token 只从环境变量读取，不写 YAML，不返回给浏览器。
- `/api/config` 仅返回 `has_token`。
- agent 仍不接触 GitHub token。
- Web GUI 可操作本地 SSH key 和 `~/.ssh/config`，因此不应暴露到不可信网络。

## 15. MVP 实现顺序

1. `codespace/client/config.py`：读取并校验 YAML 配置。
2. `codespace/client/service.py`：抽出 CLI / Web 共享的 list/create/delete 编排。
3. `codespace/client/web.py`：实现本地 FastAPI API 和 operation 管理。
4. `codespace/client/static/`：实现原生 HTML / JS / CSS Dashboard。
5. 测试：配置校验、Dashboard 聚合、创建 operation、创建失败回滚、删除流程。

## 16. 后续增强

- SSE 替代前端轮询 operation。
- 为本地缺失 alias 的远端容器补建本地 SSH alias。
- 支持多 GitHub token profile。
- 支持 IDE deep link，例如 VS Code / Cursor Remote SSH。
- 支持容器日志、健康检查、agent 分组和操作历史。
