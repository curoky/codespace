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
- 支持从配置文件读取 create templates，在 Dashboard 中展示并一键填充创建表单。
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
- 不提供模板编辑 UI；模板只通过手动编辑 `config.yaml` 维护，Web GUI 只读取和使用。

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

Web GUI 后端启动时只需要指定 Web 服务端口：

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

前端源码位于 `codespace/client/webui/`，由 pnpm 管理依赖并通过 Vite 构建到
`codespace/client/static/`：

```bash
pnpm --dir codespace/client/webui typecheck
pnpm --dir codespace/client/webui build
```

`codespace/client/static/` 是后端服务的静态资源目录，只由构建产物更新，不应手写修改。

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
  image: ghcr.io/curoky/devspace:codespace-debian12
  user: x
  workspace: default
  extra_repos:
    - curoky/ai-coding-config

github:
  token_env: GITHUB_TOKEN

agents:
  home:
    agent_url: http://10.0.0.5:8001
    ssh_host: 10.0.0.5

  office:
    agent_url: http://10.0.0.8:8001
    ssh_host: 10.0.0.8

  lab:
    agent_url: http://lab.example.com:8001
    ssh_host: lab.example.com

templates:
  devspace:
    description: devspace 主仓库默认开发环境
    agent: home
    repo: curoky/devspace
    workspace: default
    alias: home-devspace-default

  agent-lab:
    description: 使用 lab agent 和自定义镜像调试 agent
    agent: lab
    repo: curoky/devspace
    workspace: agent
    image: ghcr.io/curoky/devspace:codespace-debian12
    user: x
    extra_repos:
      - curoky/ai-coding-config
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
| `token_env` | 否 | GitHub token 所在环境变量名，默认 `GITHUB_TOKEN`；兼容误填的 GitHub token 明文但不推荐 |

不提供单独的明文 `token` 字段。为兼容用户误把 token 写入 `token_env` 的场景，client 会识别
`github_pat_` / `ghp_` 等前缀并直接使用；API 与 UI 必须只返回脱敏来源标签，不能回传 token 明文。

#### `agents.<id>`

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `agent_url` | 是 | agent HTTP API 地址 |
| `ssh_host` | 是 | client SSH 连接该 agent 宿主机时使用的 host |

#### `templates.<id>`

`templates` 是 Web GUI 的预设创建模板集合。每个模板只用于填充浏览器创建表单；点击模板后仍会
打开普通 create modal，用户可在提交前继续修改字段。模板不会直接触发创建，也不会绕过现有
GitHub token、SSH config 和 agent 创建流程。

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `description` | 否 | UI 卡片描述 |
| `agent` | 否 | 预选 agent id；不填则使用 `defaults.agent` |
| `repo` | 是 | 目标 GitHub 仓库 `owner/name` |
| `workspace` | 否 | 预填 workspace；不填则使用 `defaults.workspace` |
| `alias` | 否 | 预填 SSH alias；不填则前端按默认规则自动生成 |
| `image` | 否 | 预填 dev 镜像；不填则使用 `defaults.image` |
| `user` | 否 | 预填容器登录用户；不填则使用 `defaults.user` |
| `extra_repos` | 否 | 预填额外只读 repo 列表；不填则使用 `defaults.extra_repos` |

### 4.4 校验规则

- 配置文件必须是 YAML mapping。
- 至少配置一个 agent。
- `defaults.agent` 必须存在于 `agents`。
- agent id 必须匹配 `^[\w.-]+$`，因为它会参与默认 SSH alias 生成。
- `defaults.workspace` 必须匹配 `shared.WORKSPACE_RE`。
- `defaults.extra_repos` 每项必须匹配 `shared.REPO_RE`。
- 每个 `agent_url` 与 `ssh_host` 均不能为空。
- template id 必须匹配 `^[\w.-]+$`。
- `templates.<id>.repo` 必须匹配 `shared.REPO_RE`。
- `templates.<id>.agent` 如设置，必须存在于 `agents`。
- `templates.<id>.workspace` 如设置，必须匹配 `shared.WORKSPACE_RE`。
- `templates.<id>.extra_repos` 每项必须匹配 `shared.REPO_RE`。
- 模板的 `description`、`alias`、`image`、`user` 如设置则不能为空白字符串。
- `github.token_env` 推荐保存环境变量名；如果误填明文 token，API 只返回脱敏来源标签和 `has_token`，不得返回 token 明文。

YAML 解析建议使用 `PyYAML` 的 `yaml.safe_load`，再交给 Pydantic model 校验。

## 5. 模块划分

当前 Web GUI 相关代码集中在 `codespace/client/` 下：

```text
codespace/client/config.py       # 读取 / 校验 YAML 配置
codespace/client/service.py      # CLI 与 Web 共享的 client 编排逻辑
codespace/client/web.py          # 本地 FastAPI Web server
codespace/client/webui/          # React / Mantine Web GUI 源码与 pnpm/Vite 工程
codespace/client/static/         # Vite 构建后的 Web GUI 静态产物
```

其中 `webui/` 是源代码与前端工具链目录，`static/` 是运行时由 FastAPI 挂载的构建产物目录。

CLI 与 Web 不应复制 create / delete 编排逻辑，而应共享 `service.py`。目标依赖方向：

```text
Typer CLI ─┐
           ├── codespace.client.service ─── agent / github / ssh_config
FastAPI ───┘
```

## 6. Dashboard 能力

Dashboard 是 Web GUI 的核心页面，必须同时展示多个 agent 与其容器。

### 6.1 页面布局

Web GUI 使用 React / Mantine 构建。页面采用顶部全局操作栏 + 主工作区 + 右侧洞察列的信息架构，
把创建入口、运行中 codespaces、agent 拓扑与后台操作进度拆成稳定区域，避免所有信息线性堆叠。

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Top Bar: default agent · token status · template select · Refresh · Create   │
├────────────────────────────────────────┬─────────────────────────────────────┤
│ Main Workspace                         │ Insight Rail                        │
│ 1. Metrics                             │ Runtime status + auto refresh       │
│ 2. Codespace filters + table           │ Create templates                    │
│                                        │ Agent topology                      │
│                                        │ Operations timeline                 │
└────────────────────────────────────────┴─────────────────────────────────────┘
```

布局原则：

- **顶部只放全局动作**：`Refresh`、`Create`、token/default 摘要始终可见。
- **主列优先工作流**：codespace 过滤器和表格服务于「快速浏览 / 快速连接 / 快速删除」。
- **右列放环境洞察**：token、agent 在线状态和 operation 进度常驻，不打断主工作流。
- **表格优先**：codespace 主列表使用表格，排查和批量浏览时信息密度更高。

### 6.2 顶部 Command Bar

顶部栏始终 sticky，提供：

| 元素 | 说明 |
| --- | --- |
| 当前 Dashboard 标题 | 固定说明当前控制面范围 |
| Config summary | 展示 default agent 与 GitHub token 状态，不泄漏 token 明文 |
| Refresh | 手动刷新 `/api/dashboard` |
| Create | 打开空白创建表单 |

token 状态同时在右侧 Runtime 卡片中展开，便于用户理解 create 不可用的原因。

### 6.3 Agent Summary

对配置文件里的每个 agent 展示：

| 字段 | 说明 |
| --- | --- |
| Agent ID | `home` |
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

### 6.4 Create Templates 与 Quick Create

模板有两个入口：

1. 顶部 Command Bar 的 `Quick template` 下拉，用于常用路径的快速选中。
2. `Create Templates` 模块的模板卡片，用于浏览完整模板信息后创建。

两者都只执行「打开 create modal 并填充字段」，不会直接提交创建请求。用户仍可在 modal 中修改
agent、repo、workspace、alias、image 和 extra repos。容器登录用户来自 `defaults.user`，不在 UI 中重复暴露。

### 6.5 Codespace Table

主列展示 codespace 表格，突出日常最常用的信息与操作：

| 字段 / 操作 | 说明 |
| --- | --- |
| Repo / Agent / Workspace | 识别当前开发环境 |
| Status | 容器运行状态 |
| ID / Host:Port / User | 连接和排查所需元数据 |
| SSH command | 展示本地 alias 命令或 raw SSH 命令 |
| Delete / Purge | 删除容器或连同 workspace 清理 |

表格列用于排查和密集浏览：

| 列 | 示例 | 说明 |
| --- | --- | --- |
| Agent | `home` | 配置 profile id |
| Repo | `curoky/devspace` | 容器 label |
| Workspace | `default` | 容器 label |
| Alias | `home-devspace-default` | 本地 SSH alias，可能为空 |
| Status | `running` | agent 返回的容器状态 |
| SSH Host | `10.0.0.5` | profile `ssh_host` |
| Port | `49207` | agent 返回的 `port` |
| SSH | `ssh home-devspace-default` | 连接命令 |
| Actions | Delete / Purge | 删除操作 |

支持能力：

- 按 agent 过滤。
- 搜索 repo / workspace / alias。
- 手动刷新。
- 可选自动刷新，例如 10 秒一次。

### 6.6 Operations Timeline

右侧 operations timeline 常驻展示 WebOperation：

- `queued` / `running`：显示动画进度条，保留在列表中并持续轮询。
- `succeeded`：显示完成状态，并触发 Dashboard 刷新。
- `failed`：显示错误详情，用户可保留用于排查，或点击 `Clear` 清理已结束任务。

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

Agent        [home ▼]
Repo         [curoky/devspace]
Workspace    [default]
Alias        [home-devspace-default]
Image        [ghcr.io/curoky/devspace:codespace-debian12]
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
| Extra repos | `defaults.extra_repos` |

当 agent / repo / workspace 改变且用户未手动编辑 alias 时，前端自动重新生成 alias。

### 8.1 从模板创建

Dashboard 在 create 表单之外展示 `Create Templates` 卡片列表。模板来自配置文件
`templates.<id>`，Web GUI 不提供新增 / 修改 / 删除模板的 UI。

点击 `Create from template` 时：

1. 打开与普通创建相同的 `Create Codespace` modal。
2. 先加载 `defaults` 中的默认值和 agent 下拉选项。
3. 再用模板字段覆盖对应表单项。
4. 若模板提供 `alias`，关闭自动 alias 并使用模板值；否则保持自动 alias，并按
   `<agent-id>-<repo-name>-<workspace>` 生成。
5. 用户仍需点击 `Create` 才真正提交创建请求。

模板字段 fallback 规则：

| 表单字段 | 模板字段 | 模板未设置时 |
| --- | --- | --- |
| Agent | `agent` | `defaults.agent` |
| Repo | `repo` | 无 fallback，模板必填 |
| Workspace | `workspace` | `defaults.workspace` |
| Alias | `alias` | 自动生成 |
| Image | `image` | `defaults.image` |
| Extra repos | `extra_repos` | `defaults.extra_repos` |

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
    "image": "ghcr.io/curoky/devspace:codespace-debian12",
    "user": "x",
    "workspace": "default",
    "extra_repos": ["curoky/ai-coding-config"]
  },
  "github": {
    "token_env": "GITHUB_TOKEN",
    "has_token": true,
    "inline_token": false
  },
  "agents": [
    {
      "id": "home",
      "agent_url": "http://10.0.0.5:8001",
      "ssh_host": "10.0.0.5"
    }
  ],
  "templates": [
    {
      "id": "devspace",
      "description": "devspace 主仓库默认开发环境",
      "agent": "home",
      "repo": "curoky/devspace",
      "workspace": "default",
      "alias": "home-devspace-default",
      "image": null,
      "user": null,
      "extra_repos": null
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
  "image": "ghcr.io/curoky/devspace:codespace-debian12",
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

class CreateTemplateConfig(BaseModel):
    id: str
    description: str | None = None
    agent: str | None = None
    repo: str
    workspace: str | None = None
    alias: str | None = None
    image: str | None = None
    user: str | None = None
    extra_repos: list[str] | None = None

class WebConfig(BaseModel):
    defaults: DefaultsConfig
    github: GithubConfig = Field(default_factory=GithubConfig)
    agents: dict[str, AgentProfile]
    templates: dict[str, CreateTemplateConfig] = Field(default_factory=dict)
```

配置摘要：

```python
class ConfigTemplateSummary(BaseModel):
    id: str
    description: str | None = None
    agent: str | None = None
    repo: str
    workspace: str | None = None
    alias: str | None = None
    image: str | None = None
    user: str | None = None
    extra_repos: list[str] | None = None
```

Dashboard：

```python
class AgentStatus(BaseModel):
    id: str
    agent_url: str
    ssh_host: str
    status: Literal["online", "offline"]
    error: str | None = None
    codespace_count: int = 0

class DashboardCodespace(BaseModel):
    agent_id: str
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
4. `codespace/client/webui/`：实现 React / Mantine Dashboard，使用 Vite 构建到 `codespace/client/static/`。
5. 配置式 create templates：读取 `config.yaml`、API 返回摘要、前端卡片展示与一键填表。
6. 测试：配置校验、Dashboard 聚合、模板摘要、创建 operation、创建失败回滚、删除流程。

## 16. 后续增强

- SSE 替代前端轮询 operation。
- 为本地缺失 alias 的远端容器补建本地 SSH alias。
- 支持模板分组、搜索或从现有 codespace 生成模板（仍应避免在 MVP 中提供复杂编辑器）。
- 支持多 GitHub token profile。
- 支持 IDE deep link，例如 VS Code / Cursor Remote SSH。
- 支持容器日志、健康检查、agent 分组和操作历史。
