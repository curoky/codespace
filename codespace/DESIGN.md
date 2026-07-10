# Codespace 设计

Codespace 是一个轻量远程开发环境方案：本地 client 提供 Web GUI，Linux agent 负责通过
rootful Podman 创建开发容器。client 管理 Git provider deploy key、本地登录 key 与 SSH config；
agent 保持无状态，不持有 GitHub / GitLab token。

> **文档维护原则**：本文是整体架构、协议、失败语义和安全边界的事实来源。Web GUI 的页面与
> API 细节见 [`WEBGUI_DESIGN.md`](./WEBGUI_DESIGN.md)，用户操作说明见 [`USAGE.md`](./USAGE.md)。

## 1. 目标与非目标

### 目标

- 通过本地 Web GUI 创建、查看、删除远程开发容器。
- Web GUI 采用项目优先信息架构：每个 create template 是一个项目，项目卡是主视图，实例是项目下的运行环境；创建、删除是次级操作。
- 每个 codespace 绑定一个 repo，并使用 repo 级 deploy key，不使用账户级 SSH key 进入容器。
- 工作区数据持久化：删除容器时默认保留 workspace，重建同一 template/instance 时可复用数据。
- 支持多 agent、多模板、多实例。
- 支持 GitHub 与 GitLab provider，provider 差异收敛在 client provider façade。
- agent 无状态；Git provider token 只保存在本地 Python Web GUI service 的进程内存中，不写入 YAML 或浏览器持久化存储。
- SSH 连接信息写入 `~/.ssh/codespace/ssh_config`，并由 `~/.ssh/config` Include，用户可以直接 `ssh <alias>` 登录。

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
  │ 在进程内存中保存 Git provider token
  │ 维护 ~/.ssh/codespace/ssh_config，并确保 ~/.ssh/config Include
  │ 注册 / 吊销 Git provider deploy key
  │
  ├──────────────▶ Agent home   ──▶ Podman containers
  ├──────────────▶ Agent office ──▶ Podman containers
  └──────────────▶ Agent lab    ──▶ Podman containers

client ── register/delete deploy key ──▶ GitHub / GitLab
```

agent 容器挂载宿主机 podman socket 到 `/tmp/podmanxd.sock`，创建的开发容器是宿主机上的兄弟容器
（Podman-out-of-Podman, PoP）。开发容器使用 host network，sshd 在宿主机网络命名空间监听随机
端口，client 使用配置中的 `ssh_host` 加返回的端口直连。

agent 镜像使用 s6/s6-rc 作为容器 init，并在默认 `user` runlevel 下托管两个 longrun 服务：

- `agent-service`：启动 `python -m codespace.agent serve`；除 workspace 根目录外，监听地址、端口和 podman socket 均在 run 脚本中固定。
- `atuin-service`：启动 `atuin server start`，默认监听 `127.0.0.1:8002`。

agent 容器启动契约是“`WORKSPACE_ROOT_HOST` 环境变量 + 可选 `ATUIN_DB_URI` 环境变量 + s6 ENTRYPOINT”，不再通过镜像 argv 传入
`serve ...`。其他运行参数固定在 s6 run 脚本中：agent 监听 `0.0.0.0:8001`，podman socket 为
`unix:///tmp/podmanxd.sock`，atuin 监听 `127.0.0.1:8002` 且关闭开放注册。

| 环境变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `WORKSPACE_ROOT_HOST` | 是 | 无 | 宿主机 workspace 根目录。 |
| `ATUIN_DB_URI` | 否 | 无 | atuin server 数据库连接串。 |

### 2.1 PoP 路径语义

`podman run -v <src>:<dst>` 的 `<src>` 由宿主机 podman service 解释，而不是 agent 容器内路径。
因此 agent 不需要挂载 workspace 根目录，只需要把配置中的 `workspace_root_host` 字符串传给
podman。工作区目录的创建、挂载、删除都围绕宿主机路径字符串进行。

### 2.2 密钥和 token 边界

- GitHub / GitLab token：用户在 Web GUI 页面填写后保存到本地 Python Web GUI service 进程内存；
  用于 deploy key 生命周期管理，不会发送给 agent，不写入 YAML 或浏览器持久化存储。
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
│   ├── config.py                # AgentConfig 校验与 workspace 宿主机路径推导
│   ├── operations.py            # 异步 create operation 内存 store
│   ├── service.py               # CodespaceProvisioner 创建编排与回滚
│   ├── containers.py            # Podman 容器生命周期、清单、就绪探测、workspace
│   ├── credentials.py           # deploy key/登录公钥 put_archive 注入与 repo clone
│   ├── podman_exec.py           # podman exec 多路复用帧解析
│   └── keys.py                  # ed25519 deploy keypair 生成
├── client/
│   ├── __main__.py              # 本地 Web GUI 启动器
│   ├── config.py                # YAML 配置模型与校验
│   ├── github.py                # GitHub deploy key 操作
│   ├── gitlab.py                # GitLab deploy key 操作
│   ├── providers/               # provider façade
│   ├── service.py               # client 编排逻辑
│   ├── ssh_config.py            # ~/.ssh/codespace/ssh_config 托管块与主 config Include 管理
│   ├── web.py                   # FastAPI Web app 与路由
│   ├── web_models.py            # Web API schema
│   ├── web_operations.py        # Web operation store
│   ├── web_projection.py        # Dashboard/config projection、Trae URL
│   ├── webui/                   # React / Radix Themes 前端源码
│   └── static/                  # Vite 构建产物
└── images/
    ├── agent/                   # agent 镜像 Dockerfile、s6 服务定义与运行脚本
    └── dev/                     # 参考开发镜像 Dockerfile、rootfs、构建脚本
```

| 路径 | 职责 |
| --- | --- |
| `shared.py` | repo/template/instance 命名、wire model、deploy key title。 |
| `agent/app.py` | agent HTTP API 路由；将创建流程委托给 provisioner。 |
| `agent/service.py` | create 编排（去重、keygen、workspace、拉镜像、建容器、注入、探测）与失败回滚。 |
| `agent/containers.py` | 容器创建、状态读取、清单/去重、SSH 就绪探测、workspace 目录准备与 purge。 |
| `agent/credentials.py` | 通过 put_archive 注入 deploy 私钥/登录公钥与 git ssh config，以及 repo clone。 |
| `images/agent/rootfs/etc/s6/s6-rc.d/agent-service/run` | s6 longrun：读取 `WORKSPACE_ROOT_HOST`，并使用固定的 agent 监听地址、端口和 podman socket 启动 agent CLI。 |
| `images/dev/rootfs/etc/s6/s6-rc.d/atuin-service/run` | s6 longrun：启动 `atuin server start`；agent 镜像在 Dockerfile 中直接复用该服务定义。 |
| `client/config.py` | 读取 YAML，注入 agent/template id，校验 agent、template。 |
| `client/providers/registry.py` | GitHub / GitLab deploy key register/delete façade。 |
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

参考开发镜像位于 `codespace/images/dev/`；agent 镜像资源位于 `codespace/images/agent/`。

## 5. Agent 协议

Base URL：`http://<agent-host>:<port>`，Content-Type：`application/json`。

### 5.1 `POST /codespaces`

创建请求：

```json
{
  "repo": "owner/name",
  "provider": "github",
  "template": "api",
  "instance": "dev",
  "login_pubkey": "ssh-ed25519 AAAA... user@client",
  "image": "ghcr.io/curoky/devspace:codespace-debian12"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `repo` | Git provider repo 路径，如 `owner/name`。 |
| `provider` | `github` 或 `gitlab`。 |
| `template` | 模板 id，参与 workspace 命名。 |
| `instance` | 模板下的实例名，参与 workspace 命名。 |
| `login_pubkey` | client 本地登录公钥，用于 SSH 登录容器。 |
| `image` | 开发镜像。 |

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

1. 校验请求：repo、provider、template、instance、login public key、image。
2. 生成 codespace id 和 operation id。
3. 计算 workspace 目录名：`codespace-<repo-slug>-<template>-<instance>-<hash8>`。
4. 向内核申请一个当前空闲 TCP 端口作为 sshd 端口。
5. 生成 repo deploy keypair；私钥待注入，公钥待返回给 client。
6. 使用 podman-py 创建开发容器：
   - `name=shared.container_name(cs_id)`；
   - `network_mode="host"`；
   - `environment={"SSHD_PORT": str(port)}`；`SSHD_PORT` 始终由 agent 分配的端口；
   - labels 写入 repo/provider/template/instance/user/image/port 等元数据；
   - bind mount workspace 到 `/workspace`。
7. 等待容器 running。
8. 容器内 root 执行 `chown -R <user> /workspace` 修正 bind mount 属主。
9. 通过 `put_archive` 把 SSH 物料注入登录用户 `~/.ssh/`：
   - deploy private key；
   - git SSH config；
   - `authorized_keys`；
   - 必要权限和属主。
10. 返回 codespace payload，丢弃内存中的 deploy private key。

创建前 agent 会根据 Podman container labels 检查是否已存在相同 `repo/template/instance` 的容器；
workspace 目录是否存在不参与这个重复判断。若报 `codespace already exists for repo/template/instance`，
说明 agent 连接的 Podman service 中仍存在带相同 labels 的容器，错误信息会包含 existing id、容器名
和状态，便于清理 stale container。

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
3. 请求 agent `POST /codespaces`。
4. 轮询 agent operation，直到得到 `shared.Codespace`。
5. 使用 provider façade 注册 deploy key：
   - GitHub 使用 PyGithub；
   - GitLab 使用 GitLab API；
   - key title 均为 `codespace-<cs_id>`。
6. 请求 agent `POST /codespaces/{id}/clone` clone 主 repo。
7. 写入本地 `~/.ssh/codespace/ssh_config` 托管块，并确保 `~/.ssh/config` 包含 `Include ~/.ssh/codespace/ssh_config`。

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
5. 删除本地 `~/.ssh/codespace/ssh_config` 中的 SSH config 托管块。
6. 删除本地登录 keypair。

若本地 alias 缺失，仍允许删除远端容器；此时只能根据 Web 请求里的 repo 尽力吊销主 repo deploy
key，并向用户返回 warning。若 provider deploy key 吊销失败（例如 GitLab fine-grained token 缺少
delete deploy key 权限），删除流程仍继续删除远端容器和本地 SSH 物料，并把吊销失败作为 warning
返回给 Web GUI。

## 9. SSH config 专用文件与托管块

Codespace 的 Host blocks 统一写入专用文件 `~/.ssh/codespace/ssh_config`。主 `~/.ssh/config` 只需要
包含：

```sshconfig
Include ~/.ssh/codespace/ssh_config
```

如果检测到旧版本直接写在 `~/.ssh/config` 中的 codespace 托管块，client 会自动迁移到
`~/.ssh/codespace/ssh_config`，并从主 config 删除这些托管块。

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
- 默认删除容器不删目录，purge 才删除目录；
- purge 时 agent 通过 helper container 挂载 workspace 父目录并删除目标 workspace 目录本身，避免只清空目录内容后留下空目录。

## 11. 状态来源

| 信息 | 存放位置 | 读取方式 |
| --- | --- | --- |
| repo/provider/template/instance/image/port | Podman container labels | agent list / operation |
| workspace 数据 | 宿主机 bind mount 目录 | Podman mount |
| deploy key | GitHub / GitLab | client 按 title 反查 |
| Git provider token | client Web GUI 进程内存 | 创建/删除时由本地 Web GUI 读取 |
| login private key | `~/.ssh/codespace/<alias>` | SSH 登录 |
| SSH alias metadata | `~/.ssh/codespace/ssh_config` 托管块 | dashboard/delete projection |
| Web operation | client 进程内存 | `/api/operations/{id}` |

agent 重启后不会丢失容器状态；Web GUI 重启后 operation 历史丢失，但 Dashboard 会重新通过 agent
list 发现现存 codespace。agent 内存中的 failed operation 不参与重复实例判断；重复判断只来自 Podman
容器 labels，因此排查 stale instance 时应使用 agent 同一个 podman socket 查看容器列表。

## 12. Git provider 抽象

Git provider 差异集中在 `codespace/client/providers/registry.py`：

| 能力 | GitHub | GitLab |
| --- | --- | --- |
| 默认 SSH host | `github.com` | `gitlab.com` |
| register deploy key | PyGithub | python-gitlab |
| delete deploy key | 按 title 反查删除 | 按 title 反查删除 |

上层 `service.py` 和 `web.py` 不直接分支 GitHub/GitLab，统一通过 provider façade 执行 deploy key
操作；Git clone SSH host 由 `shared.default_git_host(provider)` 推导。

GitLab token 可以是普通 Personal Access Token，也可以是 Fine-grained personal access token。
Fine-grained token 只需要覆盖目标 project，并授予 Deploy Key 相关 REST API 权限。GitLab client
使用 python-gitlab 的 lazy project object，避免先请求 `GET /projects/:id`；这样即使 token 只允许
project deploy key 的 list/create/delete endpoint，也能完成 codespace 的 deploy key 生命周期。

## 13. 安全模型

### 13.1 已保证

- token 不写入 YAML，不发送给 agent；仅保存在本地 Python Web GUI service 进程内存中。
- agent 不持有 Git provider token。
- deploy key title 使用 `codespace-<id>`，便于删除时对账。
- deploy key 只授权单个 repo。
- Web GUI 默认只监听 localhost。
- agent 只操作 `codespace-` 前缀容器。

### 13.2 已接受风险

- rootful podman socket 等价宿主机 root；agent 挂载该 socket 即拥有强权限。
- 开发容器内存在 deploy private key，宿主机 root 在容器存活期可读取。
- agent HTTP 默认无鉴权，能访问 agent 端口者可创建/删除受管容器。
- Web GUI 进程会在内存中保存 provider token，并能访问本地 SSH key、`~/.ssh/config` 和 `~/.ssh/codespace/ssh_config`，不可暴露给不可信网络。

## 14. 失败与一致性

create 是跨系统两段操作：agent 建容器 + client 注册 deploy key。系统使用 codespace id 作为单一
关联键：

- 容器名：`codespace-<id>`；
- Podman label：`codespace.id=<id>`；
- deploy key title：`codespace-<id>`；
- SSH config 注释：`codespace-id: <id>`，位于 `~/.ssh/codespace/ssh_config`。

这使得删除和回滚不依赖额外数据库。即使 Web GUI 进程重启，也可以通过 agent list + 专用 SSH
config 托管块 + Git provider key title 重新对齐状态。

## 15. 验证要求

相关变更至少运行：

```bash
uv run pytest codespace/tests
uv run ruff check codespace
pnpm --dir codespace/client/webui typecheck
pnpm --dir codespace/client/webui build
```

如果修改依赖，额外运行：

```bash
uv lock --check
```

## 16. 后续增强

- 为本地缺失 alias 的远端容器补建 SSH alias。
- agent 分组、标签。
- 容器日志和健康检查。
- 空闲自动停止 / TTL / GC。
- 支持更多 Git provider。
