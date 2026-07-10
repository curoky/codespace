# Codespace Web GUI 设计

本文档描述当前 Web GUI 形态。client 不再维护 create/list/delete CLI，只保留
`python -m codespace.client` 作为本地 Web GUI 启动器。

> 底层 agent 协议、Podman 编排、密钥注入、回滚语义见 [`DESIGN.md`](./DESIGN.md)。本文聚焦
> Web GUI、YAML 配置、Dashboard projection、Web API 与前端交互。

## 1. 目标与非目标

### 目标

- 本地启动 Web GUI，默认监听 localhost。
- 从一个 YAML 配置文件读取多个 agent profile、provider 和 create templates。
- Dashboard 聚合展示所有 agent 在线状态、codespace 实例、后台 operation。
- 以连接为核心：codespace 实例卡片是主视图，可直接 Open in Trae / 复制 SSH；创建、删除是次级操作。
- 支持创建 codespace，并展示完整创建进度。
- 支持删除 codespace，可选择是否 purge workspace。
- 支持 GitHub / GitLab provider，token 通过顶部 Tokens 弹窗填写并保存到本地 Python Web GUI service 进程内存。
- 复用 client service：login key、deploy key、clone、SSH config、回滚。

### 非目标

- 不提供远程多用户控制台。
- 不提供模板编辑 UI；模板通过手动编辑 YAML 维护。
- 不持久化 Web operation 历史；server 重启后通过 agent list 重新发现实际容器。
- 不持久化 token 到磁盘或浏览器存储；刷新页面后会保留 service 内存中的 token 状态，重启 Web GUI service 后需要重新填写。
- 不提供浏览器内 terminal。

## 2. 总体架构

```text
Browser
  │ HTTP localhost
  ▼
Local FastAPI Web GUI
  │ 读取 ~/.config/codespace/config.yaml
  │ 管理 ~/.ssh/codespace/ssh_config，并确保 ~/.ssh/config Include
  │ 使用 service 进程内存中的 Git provider token 注册 / 吊销 deploy key
  │
  ├──────────────▶ Agent home   ──▶ Podman containers
  ├──────────────▶ Agent office ──▶ Podman containers
  └──────────────▶ Agent lab    ──▶ Podman containers
```

Web GUI 是本地控制面，不部署到 agent。agent 离线不会阻塞其它 agent 展示；Dashboard 对每个
agent 独立请求并聚合结果。

## 3. 启动方式

```bash
uv run python -m codespace.client
```

环境变量：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CODESPACE_WEB_HOST` | `127.0.0.1` | Web GUI 监听地址 |
| `CODESPACE_WEB_PORT` | `8765` | Web GUI 监听端口 |
| `CODESPACE_CONFIG` | `~/.config/codespace/config.yaml` | YAML 配置路径 |

若监听地址不是 `127.0.0.1` 或 `localhost`，启动器必须打印安全警告，因为 Web GUI 能访问本地
SSH key、`~/.ssh/config`、`~/.ssh/codespace/ssh_config`，并会在进程内存中保存 provider token。

前端源码位于 `codespace/client/webui/`，构建产物输出到 `codespace/client/static/`：

```bash
pnpm --dir codespace/client/webui typecheck
pnpm --dir codespace/client/webui build
```

`static/` 是运行时静态资源目录，正常情况下只由 Vite build 更新。

## 4. YAML 配置

### 4.1 路径与优先级

```text
CODESPACE_CONFIG > ~/.config/codespace/config.yaml
```

配置文件必须是 YAML mapping。

### 4.2 示例

```yaml
defaults:
  agent: home
  image: ghcr.io/curoky/devspace:codespace-debian12

agents:
  home:
    agent_url: http://10.0.0.5:8001
    ssh_host: 10.0.0.5

  office:
    agent_url: http://127.0.0.1:8001
    ssh_host: dev-host
    ssh_proxy: true
    ssh_proxy_host: office-bastion

templates:
  devspace:
    description: devspace 主仓库默认开发环境
    agent: home
    provider: github
    repo: curoky/devspace
    image: ghcr.io/curoky/devspace:codespace-debian12

  service-api:
    description: GitLab API 服务
    agent: office
    provider: gitlab
    repo: group/service-api
```

### 4.3 字段说明

#### `defaults`

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `agent` | 是 | 默认选中的 agent profile id。 |
| `image` | 是 | 默认开发镜像。 |

#### `agents.<id>`

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `agent_url` | 是 | agent HTTP API 地址。 |
| `ssh_host` | 是 | SSH 登录 codespace 时使用的宿主机 host。 |
| `ssh_proxy` | 否 | 是否通过 SSH tunnel 访问 agent HTTP API。 |
| `ssh_proxy_host` | 否 | SSH tunnel bastion host；`ssh_proxy=true` 时必填。 |

#### `templates.<id>`

模板只用于填充创建表单，不会自动提交创建请求。

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `description` | 否 | UI 展示描述。 |
| `agent` | 否 | 预选 agent；不填则使用 `defaults.agent`。 |
| `provider` | 否 | `github` 或 `gitlab`，默认 `github`。 |
| `repo` | 是 | 目标 repo 路径，如 `owner/name`。 |
| `image` | 否 | 模板默认镜像；不填使用 `defaults.image`。 |

### 4.4 校验规则

- 至少配置一个 agent。
- `defaults.agent` 必须存在于 `agents`。
- agent id 与 template id 必须匹配 `^[\w.-]+$`。
- `agent_url`、`ssh_host` 不能为空。
- `ssh_proxy=true` 时必须配置 `ssh_proxy_host`。
- `templates.<id>.repo` 必须匹配 `shared.REPO_RE`。
- `templates.<id>.agent` 如设置，必须存在于 `agents`。

## 5. 后端模块划分

```text
codespace/client/__main__.py          # Web GUI 启动器
codespace/client/config.py            # YAML 配置模型与加载
codespace/client/providers/           # GitHub / GitLab provider façade
codespace/client/service.py           # client 编排：agent、deploy key、clone、ssh config
codespace/client/web.py               # FastAPI app 与路由
codespace/client/web_models.py        # Web API Pydantic schema
codespace/client/web_operations.py    # Web operation store
codespace/client/web_projection.py    # config/dashboard projection 与 Trae URL
codespace/client/webui/               # React / Radix Themes 前端源码
codespace/client/static/              # Vite 构建产物
```

依赖方向：

```text
web.py ──▶ service.py ──▶ providers / ssh_config / agent API
  │
  ├──▶ web_models.py
  ├──▶ web_operations.py
  └──▶ web_projection.py
```

`web.py` 只保留路由和 app 创建；schema、operation store、projection 均独立模块化。

## 6. Dashboard 信息架构

页面使用 React / Radix Themes（light appearance），采用「连接优先」信息架构：codespace 实例卡片
是主视图，用户最高频的动作是连接一个已有环境，因此这些动作直达卡片；创建、删除、token 管理
被降级为次级入口，不占据主视觉。

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Top Bar: Codespace · Tokens 弹窗 · Refresh · New codespace                    │
├──────────────────────────────────────────────────────────────────────────────┤
│ Agent Bar: agent 状态 chips（点击过滤）· 搜索框（repo/instance/alias）        │
├──────────────────────────────────────────────────────────────────────────────┤
│ Codespace Grid（响应式 1/2/3/4 列）                                           │
│   每张卡片：instance · status · template · provider · repo · agent · alias    │
│   ready 卡片动作：Open in Trae · Copy SSH · ⋯（Delete container / workspace） │
│   进行中的 operation 也渲染为卡片：进度条 · stage · 失败可 Dismiss           │
└──────────────────────────────────────────────────────────────────────────────┘
```

设计原则：

- 连接是主线：ready codespace 卡片把 Open in Trae 和 Copy SSH 做成一等动作。
- 进行中的 create operation 和 ready codespace 合并进同一 grid（按 `agent+template+instance`
  去重），operation 卡片排在前面，完成后由 dashboard 刷新替换为真实 codespace。
- 创建、删除、token 管理是次级操作：New codespace 是弹窗，删除收进卡片的 ⋯ 菜单，token 收进
  顶部 Tokens 弹窗并显示已保存数量，避免创建失败时用户不知道原因。
- 过滤保持轻量：只有 agent chips 过滤 + 文本搜索，不做状态过滤和多维排序（容器数量通常是个位数）。
- 离线 agent 不阻塞其它 agent，其错误在 Agent Bar 以 callout 展示。
- 缺少本地 alias 的远端容器仍可展示 raw SSH 命令（Copy SSH 回退到 `raw_ssh_command`）。

## 7. Template / Instance 模型

实例身份由三元组确定：

```text
agent + template + instance
```

本地 SSH alias 自动生成：

```text
<agent>-<template>-<instance>
```

例如：

```text
home-devspace-default
office-service-api-debug
```

创建表单是一个弹窗（New codespace）：用户在可过滤的 template 列表中选择 template，填写 instance。
repo、provider、agent、image 等字段由 template 和 defaults 填充，Web GUI 不提供无 template 的空白
创建入口。打开弹窗时会为选中 template 自动建议一个未占用的 instance 名。GitHub / GitLab token 在顶部
Tokens 弹窗填写并保存到 service 进程内存中，创建时按 template 的 provider 取对应 token；token 未保存
时弹窗内直接提示。

## 8. Dashboard projection

`GET /api/dashboard` 聚合三类数据：

1. agent list 结果：每个 agent 独立请求 `/codespaces`。
2. 本地 SSH config projection：从 `~/.ssh/codespace/ssh_config` 根据 `codespace-id + codespace-agent` 反查 alias。
3. Web operation store：本进程内 queued/running/succeeded/failed 操作。

### 8.1 AgentStatus

| 字段 | 说明 |
| --- | --- |
| `id` | agent id。 |
| `agent_url` | HTTP API 地址。 |
| `ssh_host` | SSH 登录 host。 |
| `ssh_proxy_host` | SSH proxy bastion，可为空。 |
| `ssh_proxy` | 是否启用 SSH HTTP tunnel。 |
| `status` | `online` / `offline`。 |
| `error` | 离线或请求失败原因。 |
| `codespace_count` | 该 agent 返回的 codespace 数。 |

### 8.2 DashboardCodespace

| 字段 | 说明 |
| --- | --- |
| `agent_id` | 所属 agent。 |
| `id` | codespace id。 |
| `repo` | 主 repo。 |
| `provider` | Git provider。 |
| `template` | template id。 |
| `instance` | instance name。 |
| `alias` | 本地 SSH alias，可能为空。 |
| `raw_ssh_command` | `ssh <user>@<ssh_host> -p <port>`。 |
| `trae_url` | Trae Remote-SSH deep link。 |

### 8.3 Trae URL

Trae deep link 由 `web_projection.trae_remote_ssh_url(...)` 生成。若有 alias，remote authority 使用
alias；否则使用 `user@host:port`。路径默认打开 `/workspace/<repo-name>`。

## 9. 创建流程与 WebOperation

Web GUI 自己维护一层 operation，因为一次创建横跨 agent、Git provider、本地 SSH config。

WebOperation 字段：

| 字段 | 说明 |
| --- | --- |
| `id` | Web operation id。 |
| `agent_id` | 目标 agent。 |
| `alias` | 预计本地 alias。 |
| `repo` | 目标 repo。 |
| `provider` | Git provider。 |
| `template` | template id。 |
| `instance` | instance name。 |
| `status` | `queued` / `running` / `succeeded` / `failed`。 |
| `stage` | 当前阶段文本。 |
| `error` | 失败原因。 |
| `created_at` / `updated_at` | 时间戳。 |

典型 stage：

```text
queued
starting
preparing login key
requesting agent creation
agent: queued
agent: creating container
agent: injecting credentials
agent: ready
registering deploy key: owner/name
cloning repo into workspace
writing ssh config
ready
failed
```

## 10. 删除流程

Dashboard 每个 instance 提供删除入口：

- Delete container：删除容器，保留 workspace。
- Delete workspace：删除容器并删除 workspace 目录本身。

后端流程：

1. 根据 `agent_id + codespace_id` 查找本地 SSH config entry。
2. 确定 provider：优先 SSH config entry；其次根据 repo 匹配 template；最后使用默认 provider。
3. 从 service 内存读取对应 provider token；token 缺失时跳过吊销并返回 warning。
4. 调 agent `DELETE /codespaces/{id}`。
5. 清理 `~/.ssh/codespace/ssh_config` 中的 SSH config block 和 login key。
6. 返回 warning（如 token 缺失、alias 缺失或 provider deploy key 吊销失败）。deploy key 吊销失败
   不阻断容器和 workspace 删除。

创建时 Web GUI 会基于当前 Dashboard 和本地 operation 列表检查 `agent/template/instance` 是否已存在：
打开创建弹窗时会为 `default` 冲突自动建议 `default-2`、`default-3` 等名称；提交前也会阻止已知重复。
最终一致性仍由 agent 的 Podman label 去重保证。若 agent 返回 `codespace already exists for
repo/template/instance`，说明 agent 使用的 Podman service 里仍有同 repo/template/instance 的容器；
workspace 目录存在本身不会触发该错误。

## 11. Web API

Web API 只服务本地浏览器，不是远程公共 API。

### 11.1 `GET /api/config`

返回配置摘要，不包含 token：

```json
{
  "default_agent": "home",
  "defaults": {"image": "ghcr.io/curoky/devspace:codespace-debian12"},
  "agents": [
    {
      "id": "home",
      "agent_url": "http://10.0.0.5:8001",
      "ssh_host": "10.0.0.5",
      "ssh_proxy_host": null,
      "ssh_proxy": false
    }
  ],
  "templates": [
    {
      "id": "devspace",
      "description": "devspace 主仓库默认开发环境",
      "agent": "home",
      "provider": "github",
      "repo": "curoky/devspace",
      "image": null
    }
  ]
}
```

### 11.2 `GET /api/dashboard`

返回 agent、codespaces、operations 三段数据。

### 11.3 `GET /api/provider-tokens`

返回各 provider 的 token 是否已保存到 service 内存，不返回 token 明文：

```json
{
  "github": {"has_token": true},
  "gitlab": {"has_token": false}
}
```

### 11.4 `PUT /api/provider-tokens/{provider}`

保存 provider token 到本地 Python Web GUI service 进程内存。`provider` 为 `github` 或 `gitlab`。
GitLab provider 可使用普通 Personal Access Token，也可使用 Fine-grained personal access token；
Fine-grained token 需要覆盖目标 project，并授予 Deploy Key 相关 REST API 权限。

请求：

```json
{"token": "github_pat_xxx"}
```

返回值同 `GET /api/provider-tokens`。

### 11.5 `POST /api/agents/{agent_id}/codespaces`

请求：

```json
{
  "repo": "curoky/devspace",
  "provider": "github",
  "template": "devspace",
  "instance": "default",
  "image": "ghcr.io/curoky/devspace:codespace-debian12"
}
```

创建时后端按请求中的 `provider` 从 service 内存读取 token；如果 token 未保存，返回错误。

返回：

```json
{"operation_id": "web-op-123"}
```

### 11.6 `GET /api/operations/{operation_id}`

查询单个 Web operation。

### 11.7 `GET /api/operations/stream`

Server-Sent Events 流，前端订阅它获得 operation 实时更新，取代逐 operation 轮询。响应
`Content-Type: text/event-stream`，每条消息是一个序列化后的 WebOperation JSON：

```text
data: {"id": "web-op-123", "status": "running", "stage": "cloning repo into workspace", ...}
```

服务端每秒对 `operations.list()` 做一次快照，只推送序列化结果发生变化的 operation；订阅建立时
先发送当前全量，便于中途加入的浏览器补齐状态。此路由声明在 `/api/operations/{operation_id}` 之前，
避免 `stream` 被当作 operation_id 匹配。该方案不改动后台创建线程与 operation store（保持线程模型
简单），代价是最多约 1s 延迟。

### 11.8 `DELETE /api/operations`

清理已完成 operation，保留 queued/running。

### 11.9 `DELETE /api/agents/{agent_id}/codespaces/{codespace_id}`

参数：

```text
repo=<owner/name>
purge=false|true
```

删除时后端根据 SSH config 或 template 推导 provider，并从 service 内存读取对应 token；如果 token
未保存，则跳过 deploy key 吊销并返回 warning。

返回：

```json
{
  "ok": true,
  "workspace_removed": false,
  "warning": null
}
```

## 12. 并发与超时

- Dashboard 并发请求所有 agent。
- 单个 agent 请求使用短超时，失败只影响该 agent。
- Web operations 存在本进程内存中，用锁保护并发读写。
- 创建操作在后台线程执行，HTTP 请求快速返回 operation id。
- 前端通过 `/api/operations/stream` SSE 订阅 operation 更新；operation 进入 succeeded/failed 时前端刷新 Dashboard，确保远端真实状态覆盖本地估计。

## 13. 前端模块

```text
webui/src/main.tsx              # App 状态、页面组合、create/delete 交互
webui/src/types.ts              # API 与视图类型（含 InstanceCard）
webui/src/api.ts                # request/fetch 封装 + openOperationStream（SSE）
webui/src/utils.ts              # alias、状态颜色、连接命令、instance 名建议等工具
webui/src/styles.css            # 少量布局类（sticky bar、grid 卡片、toast）
webui/src/hooks/useDashboard.ts # config/dashboard/operations/token 状态，订阅 SSE
webui/src/hooks/useToast.ts     # toast 状态
webui/src/components/           # TopBar / TokenPopover / AgentBar /
                                #   CodespaceGrid / CodespaceCard / CreateDialog
```

组件划分围绕连接优先 IA：`CodespaceGrid` 把 codespaces 与进行中的 operation 合并成卡片列表，
`CodespaceCard` 承载连接/删除动作，`CreateDialog` 与 `TokenPopover` 承载次级操作。样式主要交给
Radix Themes token，`styles.css` 只保留 sticky bar、grid 卡片最小高度和 toast 定位等少量布局类。

## 14. 安全约束

- token 只保存在本地 Python Web GUI service 进程内存中，不写入 YAML，也不持久化到 localStorage/sessionStorage。
- `/api/config` 不返回 token 值。
- `/api/provider-tokens` 只返回是否已保存 token，不返回 token 明文。
- agent 不接收 token。
- Web GUI 默认只监听 localhost。
- 非 localhost 监听必须提示风险。
- 不要把 Web GUI 暴露到不可信网络。

## 15. 后续增强

- 为缺失本地 alias 的远端容器补建 SSH alias。
- agent 分组、标签。
- operation 历史持久化。
- 容器日志、健康检查、资源指标。
