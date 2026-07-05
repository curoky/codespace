# Codespace 设计

Codespace 是一个轻量远程开发环境方案：本地 client 提供 Web GUI，Linux agent 负责通过
rootful Podman 创建开发容器。client 管理 Git provider deploy key、本地登录 key 与
`~/.ssh/config`；agent 保持无状态，不持有 GitHub / GitLab token。

> **文档维护原则**：本文是整体架构、协议、失败语义和安全边界的事实来源。Web GUI 的页面与
> API 细节见 [`WEBGUI_DESIGN.md`](./WEBGUI_DESIGN.md)，用户操作说明见 [`USAGE.md`](./USAGE.md)。

## 1. 目标与非目标

### 目标

- 通过本地 Web GUI 创建、查看、删除远程开发容器。
- 主列表以 template 为核心，template 下展开多个 instance。
- 每个 codespace 绑定一个 repo，并使用 repo 级 deploy key，不使用账户级 SSH key 进入容器。
- 工作区数据持久化：删除容器时默认保留 workspace，重建同一 template/instance 时可复用数据。
- 支持多 agent、多模板、多实例。
- 支持 GitHub 与 GitLab provider，provider 差异收敛在 client provider façade。
- agent 无状态；所有敏感 token 只存在于 client 本地进程。
- SSH 连接信息写入本地 `~/.ssh/config` 托管块，用户可以直接 `ssh <alias>` 登录。

### 非目标

- 多租户鉴权 / RBAC。
- agent HTTP TLS。
- 容器休眠、自动停止、计费语义。
- 浏览器内 terminal、日志流、文件浏览器。
- 继续维护 create/list/delete CLI。client 入口只负责启动本地 Web GUI。

## 2. 总体拓扑

```text
Browser
  │ HTTP localhost
  ▼
Local client Web GUI (FastAPI + React)
  │ 读取本地 config.yaml
  │ 读取 Git provider token 环境变量
  │ 维护 ~/.ssh/config 与 ~/.ssh/codespace
  │ 注册 / 吊销 Git provider deploy key
  │
  ├──────────────▶ Agent home   ──▶ Podman containers
  ├──────────────▶ Agent office ──▶ Podman containers
  └──────────────▶ Agent lab    ──▶ Podman containers

client ── register/delete deploy key ──▶ GitHub / GitLab
```

agent 容器挂载宿主机 `/run/podman/podman.sock`，创建的开发容器是宿主机上的兄弟容器
（Podman-out-of-Podman, PoP）。开发容器使用 host network，sshd 在宿主机网络命名空间监听随机
端口，client 使用配置中的 `ssh_host` 加返回的端口直连。

### 2.1 PoP 路径语义

`podman run -v <src>:<dst>` 的 `<src>` 由宿主机 podman service 解释，而不是 agent 容器内路径。
因此 agent 不需要挂载 workspace 根目录，只需要把配置中的 `workspace_root_host` 字符串传给
podman。工作区目录的创建、挂载、删除都围绕宿主机路径字符串进行。

### 2.2 密钥和 token 边界

- GitHub / GitLab token：只在 client 本地读取，用于 deploy key 生命周期管理。
- deploy private key：由 agent 生成后注入开发容器，不返回 client，不写 agent 磁盘。
- login key：由 client 本地生成，公钥发送给 agent 注入 `authorized_keys`，私钥保留在
  `~/.ssh/codespace/<alias>`。

## 3. 组件与职责

```text
codespace/
├── shared.py                    # 两端协议模型、常量、命名 helper
├── agent/
│   ├── __main__.py              # agent CLI：serve
│   ├── app.py                   # agent FastAPI app、operation 路由
│   ├── podman_ops.py            # Podman 编排、workspace、put_archive 注入
│   ├── keys.py                  # ed25519 deploy keypair 生成
│   ├── Dockerfile               # agent 镜像
│   └── run-agent.sh             # 参考启动脚本
├── client/
│   ├── __main__.py              # 本地 Web GUI 启动器
│   ├── config.py                # YAML 配置模型与校验
│   ├── github.py                # GitHub deploy key 操作
│   ├── gitlab.py                # GitLab deploy key 操作
│   ├── providers/               # provider façade
│   ├── service.py               # client 编排逻辑
│   ├── ssh_config.py            # ~/.ssh/config 托管块管理
│   ├── web.py                   # FastAPI Web app 与路由
│   ├── web_models.py            # Web API schema
│   ├── web_operations.py        # Web operation store
│   ├── web_projection.py        # Dashboard/config projection、Trae URL
│   ├── webui/                   # React / Mantine 前端源码
│   └── static/                  # Vite 构建产物
└── image/                       # 参考开发镜像
```

| 路径 | 职责 |
| --- | --- |
| `shared.py` | repo/template/instance 命名、wire model、deploy key title。 |
| `agent/app.py` | agent HTTP API 与异步 create operation 管理。 |
| `agent/podman_ops.py` | 容器创建、状态读取、workspace 目录准备、密钥注入、删除和 purge。 |
| `client/config.py` | 读取 YAML，注入 agent/template id，校验 token env、agent、template。 |
| `client/providers/registry.py` | GitHub / GitLab token、SSH host、deploy key register/delete façade。 |
| `client/service.py` | create/delete 编排，包含回滚、clone、SSH config 写入。 |
| `client/web.py` | Web API 路由，不直接承载 projection/model/store 细节。 |
| `client/web_projection.py` | 配置摘要、Dashboard payload、Trae Remote-SSH URL 生成。 |

## 4. 开发镜像契约

开发镜像必须满足以下最小契约：

1. **sshd 端口可配置**：镜像启动后运行 sshd，并读取 `SSHD_PORT` 作为监听端口；未设置时可默认
   监听 22，便于手动调试。
2. **固定登录用户**：默认登录用户为 `x`，拥有可写 home 目录，`~/.ssh/` 可创建。
3. **工作区路径可写**：容器内 `/workspace` 可被登录用户读写，作为 repo clone 目标。
4. **包含 git 与 ssh 客户端**：容器内可以执行 `git clone` / `git push` 和 SSH 连接。
5. **不依赖项目专属 hook**：agent 通过 podman `put_archive` 注入密钥，不要求镜像内提供自定义
   启动钩子。

参考镜像位于 `codespace/image/`。

## 5. Agent 协议

Base URL：`http://<agent-host>:<port>`，Content-Type：`application/json`。

### 5.1 `POST /codespaces`

创建请求：

```json
{
  "repo": "owner/name",
  "provider": "github",
  "git_ssh_host": "github.com",
  "template": "api",
  "instance": "dev",
  "login_pubkey": "ssh-ed25519 AAAA... user@client",
  "image": "ghcr.io/curoky/devspace:codespace-debian12",
  "env": {
    "HTTP_PROXY": "http://proxy.example.com:7890",
    "NO_PROXY": "localhost,127.0.0.1"
  }
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `repo` | Git provider repo 路径，如 `owner/name`。 |
| `provider` | `github` 或 `gitlab`。 |
| `git_ssh_host` | 容器内 clone 使用的 SSH host，如 `github.com`。 |
| `template` | 模板 id，参与 workspace 命名。 |
| `instance` | 模板下的实例名，参与 workspace 命名。 |
| `login_pubkey` | client 本地登录公钥，用于 SSH 登录容器。 |
| `image` | 开发镜像。 |
| `env` | 传给开发容器进程的非敏感环境变量。 |

`env` 的约束：

- key 必须匹配 `^[A-Za-z_][A-Za-z0-9_]*$`；
- 不能覆盖系统保留变量 `SSHD_PORT`；
- value 不能包含 NUL 字符；
- 不应用于传递 token、password 等敏感凭据。

agent 返回 `202` 表示创建任务进入异步 operation：

```json
{"id": "op-id", "status": "queued", "stage": "queued"}
```

### 5.2 `GET /operations/{operation_id}`

查询 agent 创建进度。成功时 `codespace` 非空：

```json
{
  "id": "op-id",
  "status": "succeeded",
  "stage": "ready",
  "codespace": {
    "id": "abc123",
    "port": 49207,
    "user": "x",
    "container_id": "...",
    "repo": "owner/name",
    "provider": "github",
    "git_ssh_host": "github.com",
    "template": "api",
    "instance": "dev",
    "workspace_dir": "codespace-owner-name-api-dev-12345678",
    "deploy_keys": [
      {
        "repo": "owner/name",
        "provider": "github",
        "public_openssh": "ssh-ed25519 AAAA...",
        "read_only": false
      }
    ],
    "status": "running"
  }
}
```

### 5.3 `GET /codespaces`

返回 agent 上所有受管容器。agent 通过容器名前缀和 labels 发现状态，不读取本地数据库。

### 5.4 `POST /codespaces/{id}/clone`

在 agent 创建完成、client 注册 deploy key 后，由 client 触发主 repo clone。这样可以保证 clone
发生时 deploy key 已经在 Git provider 生效。

### 5.5 `DELETE /codespaces/{id}`

删除开发容器。默认保留 workspace；`?purge=true` 时删除 workspace。agent 不吊销 deploy key，
deploy key 生命周期由 client 负责。

## 6. Agent 创建流程

1. 校验请求：repo、provider、git SSH host、template、instance、login public key、image。
2. 生成 codespace id 和 operation id。
3. 计算 workspace 目录名：`codespace-<repo-slug>-<template>-<instance>-<hash8>`。
4. 向内核申请一个当前空闲 TCP 端口作为 sshd 端口。
5. 生成 repo deploy keypair；私钥待注入，公钥待返回给 client。
6. 使用 podman-py 创建开发容器：
   - `name=shared.container_name(cs_id)`；
   - `network_mode="host"`；
   - `environment={**req.env, "SSHD_PORT": str(port)}`；`SSHD_PORT` 始终由 agent 分配的端口覆盖，
     用户 env 不能覆盖；
   - labels 写入 repo/provider/git_ssh_host/template/instance/user/image/port 等元数据；
   - bind mount workspace 到 `/workspace`。
7. 等待容器 running。
8. 容器内 root 执行 `chown -R <user> /workspace` 修正 bind mount 属主。
9. 通过 `put_archive` 把 SSH 物料注入登录用户 `~/.ssh/`：
   - deploy private key；
   - git SSH config；
   - `authorized_keys`；
   - 必要权限和属主。
10. 返回 codespace payload，丢弃内存中的 deploy private key。

若 agent 创建阶段失败，agent 自行删除已创建容器。此时 deploy key 尚未注册，无需清理 Git
provider。

## 7. Client 创建流程

client Web GUI 的一次创建跨越 agent、Git provider、本地 SSH 配置三个系统：

```text
Browser POST /api/agents/{agent}/codespaces
  ↓
Web server 创建 WebOperation
  ↓ 后台线程
preparing login key
requesting agent creation
agent: queued/running/...
registering deploy key
cloning repo into workspace
writing ssh config
ready
```

详细步骤：

1. 根据 `agent-template-instance` 生成 alias。
2. 生成或复用本地登录 keypair：`~/.ssh/codespace/<alias>{,.pub}`。
3. 解析并校验创建表单中的非敏感环境变量。
4. 请求 agent `POST /codespaces`。
5. 轮询 agent operation，直到得到 `shared.Codespace`。
6. 使用 provider façade 注册 deploy key：
   - GitHub 使用 PyGithub；
   - GitLab 使用 GitLab API；
   - key title 均为 `codespace-<cs_id>`。
7. 请求 agent `POST /codespaces/{id}/clone` clone 主 repo。
8. 写入本地 `~/.ssh/config` 托管块。

### 7.1 创建回滚

- agent 创建失败：删除本地 login key。
- agent 创建成功但 deploy key 注册失败：吊销已注册 key，请求 agent 删除容器，删除本地 login key。
- clone 失败：保留错误并执行同样回滚，避免留下无法使用的容器。
- SSH config 写入失败：吊销 key，删除容器，删除本地 login key。

## 8. Client 删除流程

1. 根据 `agent_id + codespace_id` 查找本地 SSH config entry。
2. 若 entry 存在，从 entry 读取 alias、repo、provider、repos。
3. 若 token 可用，按 deploy key title 删除对应 provider 上的 deploy key。
4. 请求 agent 删除容器，必要时带 `purge=true`。
5. 删除本地 SSH config 托管块。
6. 删除本地登录 keypair。

若本地 alias 缺失，仍允许删除远端容器；此时只能根据 Web 请求里的 repo 尽力吊销主 repo deploy
key，并向用户返回 warning。

## 9. SSH config 托管块

```sshconfig
# >>> codespace <alias> >>>
# codespace-id: <id>
# codespace-repos: <owner/name>
# codespace-provider: <github|gitlab>
# codespace-agent: <agent-id>
# codespace-repo: <owner/name>
Host <alias>
    HostName <ssh-host>
    Port <port>
    User <user>
    IdentityFile ~/.ssh/codespace/<alias>
    IdentitiesOnly yes
    HostKeyAlgorithms ssh-ed25519
    StrictHostKeyChecking accept-new
    UserKnownHostsFile ~/.ssh/codespace/known_hosts
    UpdateHostKeys no
# <<< codespace <alias> <<<
```

设计要求：

- alias 由 `agent-template-instance` 自动生成，不从配置文件读取。
- `codespace-agent` 必须存在，多 agent 删除和 dashboard projection 依赖精确匹配。
- `codespace-provider` 用于删除时选择正确的 provider façade。
- `codespace-repos` 当前只包含主 repo，但保留 list 结构，便于统一 revoke 逻辑。
- 缺失本地托管块不影响 Dashboard 展示；页面会展示 raw SSH 命令。

## 10. Workspace 命名与持久化

workspace 目录名由 repo、template、instance 共同决定：

```text
codespace-<repo-slug>-<template>-<instance>-<hash8>
```

其中：

- `repo-slug`：把 `owner/name` 转为 `owner-name`；
- `hash8`：`sha256(repo + "\0" + template + "\0" + instance)` 的前 8 位；
- 同一个 repo/template/instance 稳定复用同一目录；
- 不同 template 或 instance 不共享 workspace，避免串数据；
- 默认删除容器不删目录，purge 才删除目录。

## 11. 状态来源

| 信息 | 存放位置 | 读取方式 |
| --- | --- | --- |
| repo/provider/template/instance/image/port | Podman container labels | agent list / operation |
| workspace 数据 | 宿主机 bind mount 目录 | Podman mount |
| deploy key | GitHub / GitLab | client 按 title 反查 |
| Git provider token | client 环境变量 | provider façade |
| login private key | `~/.ssh/codespace/<alias>` | SSH 登录 |
| SSH alias metadata | `~/.ssh/config` 托管块 | dashboard/delete projection |
| Web operation | client 进程内存 | `/api/operations/{id}` |

agent 重启后不会丢失容器状态；Web GUI 重启后 operation 历史丢失，但 Dashboard 会重新通过 agent
list 发现现存 codespace。

## 12. Git provider 抽象

Git provider 差异集中在 `codespace/client/providers/registry.py`：

| 能力 | GitHub | GitLab |
| --- | --- | --- |
| token env | `github.token_env` | `gitlab.token_env` |
| 默认 SSH host | `github.com` | `gitlab.ssh_host` |
| register deploy key | PyGithub | GitLab API |
| delete deploy key | 按 title 反查删除 | 按 title 反查删除 |

上层 `service.py` 和 `web.py` 不直接分支 GitHub/GitLab，统一通过 provider façade 获取 token、SSH
host 和 deploy key 操作。

## 13. 安全模型

### 13.1 已保证

- token 不写入 YAML，不发送给 agent，不返回给浏览器。
- agent 不持有 Git provider token。
- deploy key title 使用 `codespace-<id>`，便于删除时对账。
- deploy key 只授权单个 repo。
- Web GUI 默认只监听 localhost。
- agent 只操作 `codespace-` 前缀容器。

### 13.2 已接受风险

- rootful podman socket 等价宿主机 root；agent 挂载该 socket 即拥有强权限。
- 开发容器内存在 deploy private key，宿主机 root 在容器存活期可读取。
- agent HTTP 默认无鉴权，能访问 agent 端口者可创建/删除受管容器。
- Web GUI 进程能访问本地 token、SSH key 和 `~/.ssh/config`，不可暴露给不可信网络。

## 14. 失败与一致性

create 是跨系统两段操作：agent 建容器 + client 注册 deploy key。系统使用 codespace id 作为单一
关联键：

- 容器名：`codespace-<id>`；
- Podman label：`codespace.id=<id>`；
- deploy key title：`codespace-<id>`；
- SSH config 注释：`codespace-id: <id>`。

这使得删除和回滚不依赖额外数据库。即使 Web GUI 进程重启，也可以通过 agent list + SSH config
托管块 + Git provider key title 重新对齐状态。

## 15. 验证要求

相关变更至少运行：

```bash
uv run pytest codespace/tests
uv run ruff check codespace
npm --prefix codespace/client/webui run typecheck
npm --prefix codespace/client/webui run build
```

如果修改依赖，额外运行：

```bash
uv lock --check
```

## 16. 后续增强

- SSE 替代前端轮询 operation。
- 为本地缺失 alias 的远端容器补建 SSH alias。
- agent 分组、标签、搜索。
- 容器日志和健康检查。
- 空闲自动停止 / TTL / GC。
- 支持更多 Git provider。
