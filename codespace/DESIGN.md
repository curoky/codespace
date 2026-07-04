# Codespace — 自研轻量版 GitHub Codespace

一个**独立、自包含**的轻量级远程开发环境方案：macOS **客户端（client）**请求
Linux **代理（agent）**为指定的 GitHub 仓库创建一个开发容器；agent 生成一把仅授权
该仓库的临时 SSH **deploy key** 注入容器，使容器内**且仅**能拉取/推送该仓库，并返回
SSH 连接信息，client 将其写入本地 `~/.ssh/config`，用户即可 `ssh <alias>` 直接进入。

> **容器运行时**：本方案使用 **Podman（rootful）**。agent 通过挂载的
> `/run/podman/podman.sock` 与宿主机 podman service 通信，创建的开发容器是宿主机上的
> **兄弟容器**（Podman-out-of-Podman, PoP）。rootful 模式下 Podman 行为与 Docker 基本
> 一致（端口映射、bind mount 属主、exec 等）。

> **独立性原则**：本方案不依赖任何宿主项目的内部约定（不假设特定基础镜像、特定容器
> 用户/uid、特定 init 系统或既有的密钥注入钩子）。它对"开发容器镜像"只提出一份最小
> **契约**（见 §3），任何满足契约的镜像均可使用。
>
> **文档维护**：本文件是该方案的单一事实来源，任何架构 / 协议 / 契约改动都必须在同一次
> 变更中同步更新本文件。

## 1. 目标与非目标

### 目标
- macOS 上一条命令即可获得一个开箱即用、可 SSH 直连、绑定到指定 GitHub 仓库的开发容器。
- 容器**能且仅能** pull/push 该单一仓库（仓库级 deploy key，绝不使用账户级 token）。
- 工作区数据**持久化**：删除容器后重建，代码与改动仍在。
- 完全自包含，不与任何既有项目的运行时机制耦合。

### 非目标（v1）
- 多租户鉴权 / RBAC（假定运行在可信内网）。
- TLS 传输加密（见 §11 威胁模型，已接受）。
- 容器休眠 / 自动停止 / 计费语义。
- Web UI，仅提供 CLI。

## 2. 拓扑结构

```
 macOS 主机                          Linux 主机 (podman, rootful)
 ----------                          ---------------------------
 ┌────────────┐                     ┌──────────────────────────┐
 │  client    │  HTTP (REST/JSON)   │  agent 容器 (PoP)         │
 │  (typer)   │ ──────────────────▶ │  - FastAPI HTTP 服务      │
 │ (--ssh-host│  {repo,image,user,  │  - podman-py (podman.sock)│
 │  自带)     │   workspace,pubkey} │  - cryptography(keypair)  │
 │ ~/.ssh/    │ ◀────────────────── │  （不接触 GitHub/无 token）│
 │  config    │  {port,id,          │                           │
 │            │   deploy_public_key}│                           │
 │ PyGithub   │                     └────────────┬─────────────┘
 │ (持 token) │                                  │ 1) podman run (兄弟容器)
 └─────┬──────┘                                  │ 2) put_archive 注入私钥
       │ 用自身 token 注册/吊销 deploy key        ▼
       │                            ┌──────────────────────────┐
       ▼                            │  开发容器                 │
 ┌────────────┐ ssh <ssh-host:port> │  满足 §3 镜像契约          │
 │  GitHub    │  ◀───────直连───────│  sshd 监听 22             │
 └────────────┘                     └──────────────────────────┘
```

- **部署模型**：Podman-out-of-Podman（PoP）。agent 容器挂载宿主机
  `/run/podman/podman.sock`；开发容器是运行在宿主机上的**兄弟容器**，其映射端口位于宿主机
  IP 上，client 可直接连接。
- **兄弟容器路径注意**：`podman run -v <src>:<dst>` 的 `<src>` 由**宿主机** podman service
  解释，而非 agent 容器内路径。工作区目录因此以宿主机路径字符串传给 podman（见 §7）。
- **密钥注入用 `put_archive`**：不依赖任何镜像内的启动钩子，agent 在容器起来后直接
  把内存 tar 写入容器 `~/.ssh/`（见 §6）。

## 3. 开发容器镜像契约

方案对"开发容器镜像"只要求以下最小契约，任何满足者皆可由 client 指定：

1. **sshd 监听 22**：容器启动后其内部运行 sshd 并监听容器端口 `22`；采用公钥认证
   （`PubkeyAuthentication yes`）。方案通过 `-p 0.0.0.0:0:22` 把它映射到宿主机随机端口。
2. **存在一个非 root 登录用户**：默认用户名 `x`（可由 client 在 create 请求的 `user`
   字段覆盖）。该用户拥有可写的家目录，`~/.ssh/` 可创建。
3. **该用户可写工作区路径**：容器内 `/workspace` 供 bind mount 挂载并可被登录用户读写。
4. **具备 git 与 ssh 客户端**：容器内可执行 `git`、`ssh`（用于 clone/push 目标仓库）。

> 方案自带一个参考镜像 `codespace/image/Dockerfile`（见 §Components）满足以上契约；用户也可
> 传入自己的镜像，只要满足契约即可。**镜像内不需要任何本方案专属的脚本或钩子**。

## Components

方案分三个顶层目录：`client/`（macOS 客户端）、`agent/`（Linux 代理）、`image/`
（参考开发镜像）；`shared.py` 为两端共用协议层。

```
codespace/
├── DESIGN.md
├── shared.py            # 两端共用：请求/响应 Pydantic 模型 + 常量
├── client/              # macOS 客户端（持 GitHub token）
│   ├── __init__.py
│   ├── __main__.py      # typer 入口（create/list/delete），调用 agent
│   ├── github.py        # PyGithub：deploy key 注册/按 title 反查删除
│   └── ssh_config.py    # 幂等维护 ~/.ssh/config 托管块（存 id/repo）
├── agent/               # Linux 代理（PoP，不接触 GitHub）
│   ├── __init__.py
│   ├── __main__.py      # typer `serve` 入口，拉起 FastAPI/uvicorn
│   ├── app.py           # FastAPI 应用与路由（POST/GET/DELETE /codespaces）
│   ├── podman_ops.py    # podman-py 容器编排 + put_archive 密钥注入
│   ├── keys.py          # cryptography：内存生成 deploy keypair
│   ├── Dockerfile       # agent 自身镜像（python + 依赖）
│   └── run-agent.sh     # 启动 agent 容器（挂 podman.sock）
└── image/               # 参考开发镜像（满足 §3 契约）
    └── Dockerfile       # FROM images/base（s6 + sshd + `x` 用户 + git）
```

| 路径 | 职责 |
| --- | --- |
| `codespace/shared.py` | 请求/响应 Pydantic 模型；常量（容器名前缀 `codespace-`、默认登录用户 `dev`、工作区路径 `/workspace`）、deploy key title helper。 |
| `codespace/client/__main__.py` | typer CLI（`create`/`list`/`delete`）；生成登录 keypair、调用 agent、注册/吊销 deploy key、编辑 ssh config。 |
| `codespace/client/github.py` | PyGithub（**client 侧、持 token**）：deploy key 注册与按 title 反查删除。 |
| `codespace/client/ssh_config.py` | 幂等地对 `~/.ssh/config` 中带标记块做 upsert/remove；存 `id`/`repo` 供删除反查。 |
| `codespace/agent/__main__.py` | typer `serve` 入口，配置校验后用 uvicorn 拉起 `app.py`。 |
| `codespace/agent/app.py` | FastAPI 应用与路由，编排 `podman_ops` 与 `keys`（不含 GitHub）。 |
| `codespace/agent/podman_ops.py` | podman-py：容器创建/端口解析/工作区目录准备 + put_archive 注入。 |
| `codespace/agent/keys.py` | cryptography：内存生成 ed25519 deploy keypair（不落盘、不碰 GitHub）。 |
| `codespace/agent/Dockerfile` | agent 自身镜像（python + 依赖）。 |
| `codespace/agent/run-agent.sh` | 启动 agent 容器的参考脚本。 |
| `codespace/image/Dockerfile` | 参考开发镜像，满足 §3 契约。 |

> **依赖**（`pyproject.toml` 运行依赖）：`typer`、`fastapi`+`uvicorn`（agent HTTP）、
> `podman`（podman-py，编排 + put_archive 注入）、`cryptography`（agent 内存生成 deploy
> keypair）、`loguru`（agent 结构化日志）、`pydantic`（随 fastapi）、`httpx`（client→agent
> HTTP）、`PyGithub`（**client 侧** deploy key 生命周期）。
> agent 镜像内**无需** podman CLI —— podman-py 直接走挂载的 podman.sock。

## 4. 通信协议（client ↔ agent）

Base URL：`http://<agent-host>:<port>`。Content-Type：`application/json`。

> **无 token 经网络**：client 独占 GitHub 交互（持有 token），agent 从不接触 GitHub、
> 也不接收 token。agent 只负责生成 deploy keypair、把私钥注入容器、把**公钥**回给 client；
> client 用自己的 token 把该公钥注册成 GitHub deploy key（见 §6/§8）。

### `POST /codespaces`
请求：
```json
{
  "repo": "owner/name",
  "image": "ghcr.io/you/dev:latest",
  "user": "dev",
  "workspace": "default",
  "login_pubkey": "ssh-ed25519 AAAA... user@mac",
  "extra_repos": ["owner/dotfiles"]
}
```
- `image`（必填）：满足 §3 契约的开发镜像，由 client 指定（agent 不再持有默认镜像）。
- `user`（可选，默认 `dev`）：容器内登录用户，由 client 指定。
- `workspace`（可选，默认 `default`）：同一 repo 下的独立工作区名，用于区分并行 codespace
  及各自的持久化目录（见 §7）。
- `extra_repos`（可选，默认 `[]`）：额外授予**只读**拉取权限的仓库（如 dotfiles）。每个额外
  repo 由 agent 单独生成一把只读 deploy keypair（见 §6/§8）。

响应 `201`：
```json
{
  "id": "8f3a1c",
  "port": 49207,
  "user": "dev",
  "container_id": "d34db33f...",
  "deploy_keys": [
    {"repo": "owner/name", "public_openssh": "ssh-ed25519 AAAA...", "read_only": false},
    {"repo": "owner/dotfiles", "public_openssh": "ssh-ed25519 BBBB...", "read_only": true}
  ],
  "repo": "owner/name",
  "workspace": "default",
  "workspace_dir": "codespace-owner-name-default-1a2b3c4d"
}
```
- **不含 SSH host**：agent 只报它能从 podman 观察到的 `port`；client 用自己的 `--ssh-host`
  （其视角下可达的宿主机地址）与该 `port` 组装连接信息。
- `deploy_keys`：agent 为主 repo（`read_only: false`）与每个额外 repo（`read_only: true`）
  各生成一把 deploy keypair 的**公钥**，client 收到后用自身 token 逐个注册为对应 repo 的
  GitHub deploy key（title 固定 `codespace-<id>`）。私钥留在容器内，绝不回传网络。
- `workspace_dir`：宿主机工作区目录名，末尾 8 位 hash 后缀避免 slug 冲突（见 §7）。

### `GET /codespaces`
响应 `200`：受管 codespace 数组（通过容器名前缀 `codespace-` 发现），每项
`{id, container_id, repo, workspace, port, user, status, workspace_dir}`
（不含 SSH host；`deploy_keys` 仅 create 返回，list 中为空）。

### `DELETE /codespaces/{id}`
删除开发容器（`podman rm -f`）；**默认保留工作区目录**（数据留存以便重建）。查询参数
`?purge=true` 时额外删除工作区目录，彻底清数据。**不涉及 GitHub、无请求体**——deploy key
由 client 在调用本接口前用自己的 token 吊销（见 §5/§8）。响应
`200 {ok: true, workspace_removed?: bool}`。删除不存在的 codespace 也返回 `200`（幂等）。

错误：校验失败（repo / image / workspace 格式、缺 pubkey）返回 `4xx {error}`；podman 失败
返回 `5xx {error}`。

## 5. 客户端行为（macOS）

`create --repo owner/name --agent http://<host>:<port> --ssh-host <ip> --token $TOKEN
        [--image ...] [--user dev] [--workspace default] [--extra-repo owner/x ...] [--alias <name>]`：
1. 生成无口令登录 keypair：`ssh-keygen -t ed25519 -f ~/.ssh/codespace/<alias> -N ""`
   （已存在则跳过）。合并额外 repo 列表 = 固定配置 `~/.config/codespace/extra-repos` +
   `--extra-repo`（去重、剔除主 repo）。
2. `POST /codespaces`，携带 repo / image / user / workspace / extra_repos / 登录公钥（**不含
   token**）。
3. 用**自己的 token** 把响应里 `deploy_keys` 的每一项注册为对应 repo 的 GitHub deploy key
   （主 repo 读写、额外 repo 只读，title 均 `codespace-<id>`）。任一注册失败：吊销已注册的
   key + 调 `DELETE /codespaces/<id>` 回滚容器 + 删本地登录 key，避免孤儿。
4. 成功后 `ssh_config.upsert(alias, ssh_host, port, user, id, repos)`——`repos` 为主 repo +
   全部额外 repo；host 用 client 自带的 `--ssh-host`，port 用响应里的 `port`。
5. 打印 `ssh <alias>` 提示。

`list`：`GET /codespaces`，表格渲染。

`delete --alias <a> [--purge] --token $TOKEN`：从 ssh config 托管块读回 `id` 与 `repos` →
用自己的 token 对每个 repo 按 title `codespace-<id>` 反查并删除 deploy key →
`DELETE /codespaces/<id>[?purge=true]` → `ssh_config.remove(alias)` → 删除本地
`~/.ssh/codespace/<alias>{,.pub}`。

### ssh config 托管块（幂等）
```
# >>> codespace <alias> >>>
# codespace-id: <id>
# codespace-repos: <owner/name>[,<owner/dotfiles>...]
Host <alias>
    HostName <host_ip>
    Port <port>
    User <user>
    IdentityFile ~/.ssh/codespace/<alias>
    StrictHostKeyChecking accept-new
    UserKnownHostsFile ~/.ssh/codespace/known_hosts
# <<< codespace <alias> <<<
```
- `id` 与 `repo` 存为注释，供 `delete` 无本地状态地吊销 deploy key（title `codespace-<id>`
  on `repo`）。`upsert` 替换同名块；`remove` 按标记删除。`<user>` 取响应中的 `user`。

## 6. 代理行为（Linux, PoP，完全无状态）

`serve --workspace-root-host /host/codespace-workspaces \
       --podman-uri unix:///run/podman/podman.sock [--host 0.0.0.0] [--port 8080]`

- **配置极简、仅 CLI**：agent 配置集中在 `AgentConfig`（pydantic `BaseModel`），仅保留两个
  **宿主机环境属性**且全部必填、无默认——`workspace_root_host`、`podman_uri`；启动时构造即
  校验（fail-fast），非法即退出。`image` / `user` / **SSH host** 等 caller 侧选择由 client
  提供（SSH host 来自 client 的 `--ssh-host`），不在 agent 暴露；`--host`/`--port` 仅为 HTTP
  绑定参数。
- **不接触 GitHub / 不持 token**：agent 无 PyGithub 依赖，全部 GitHub 交互在 client 侧。
- **agent 完全无状态**：agent 容器**只挂载** `/run/podman/podman.sock`，**不挂载**任何
  工作区目录、状态目录或卷。所有持久信息都存放在 **podman**（容器 labels）和 **GitHub**
  （deploy key，由 client 管理）里，agent 进程本身不持有任何磁盘状态，可随时重启/替换。
- `--workspace-root-host`：仅作为**宿主机路径前缀字符串**传给 podman 的 `-v` 源；agent
  自己从不访问该路径（PoP 下由宿主机 podman service 负责挂载）。
- deploy 私钥仅在请求处理期间存在于**内存**，注入后即丢弃，不落任何磁盘。

### 6.1 创建流程
1. 校验请求（`repo` 正则 `^[\w.-]+/[\w.-]+$`、`image`/`user` 非空、`workspace` 正则
   `^[\w.-]+$`、登录公钥非空）。
2. `id = <短随机十六进制>`；计算工作区目录名
   `ws = codespace-<repo-slug>-<workspace>-<hash8>`，其中 `repo-slug` 为 `owner/name` 的
   `/`→`-`，`hash8` 为 `sha256("<repo>\0<workspace>")` 的前 8 位十六进制（避免 slug 冲突，
   见 §7）；宿主机路径 `<workspace_root_host>/<ws>`。
3. **内存中**生成 deploy keypair（`cryptography` 生成 ed25519，导出 OpenSSH 格式，不写盘）；
   私钥留待注入，公钥待返回，均不落磁盘。
4. **podman-py 启动开发容器**（`client.containers.run(...)`），关键参数逐项说明：
   - `image`：client 传入、满足 §3 契约的开发镜像；`name="codespace-<id>"`：容器名带
     `codespace-` 前缀，是 agent 所有 podman 操作的作用域边界。
   - `detach=True`：后台启动并返回 `Container` 对象（agent 随后轮询其状态）。
   - `ports={"22/tcp": None}`：把容器内 sshd 的 22 端口映射到**宿主机随机端口**，client 之后
     经 `<--ssh-host>:<随机端口>` 直连。
   - `labels={codespace.id, codespace.repo, codespace.workspace, codespace.user,
     codespace.image}`：**持久元数据写进 labels**，`list`/`delete` 时从 podman 读回，agent
     无需本地存储；**注意不含 deploy key id**——GitHub 元数据只由 client 掌握，agent 靠
     `cs_id`（= 容器名/label）与 GitHub 的 key title `codespace-<id>` 关联（见 §8）。
   - `mounts=[{"type":"bind","source":<workspace_HOST>/<ws>,"target":"/workspace"}]`：把宿主机
     工作区目录 bind 到容器 `/workspace`。**PoP 关键**：`source` 是**宿主机路径**字符串，由
     宿主机 podman service 解释；**目录不存在时 podman 自动创建**（root 属主），agent 无需
     触碰宿主机文件系统。
5. **put_archive 注入（见 §6.3）**：注入**不依赖 sshd 监听**，只需容器处于 running 且登录
   用户存在。agent 轮询容器状态达到 `running` 后即：
   - 先以 `-u 0`（root）执行 `chown -R <user> /workspace`，修正 bind 目录属主（保持 agent
     无状态，chown 在容器内完成）；
   - 再用 `put_archive` 把内存中构造的 tar（deploy 私钥、git ssh config、登录公钥）写入
     登录用户的 `~/.ssh/`，随后 `chown -R <user> ~/.ssh`。
6. podman-py 读取容器 `22/tcp` 的宿主机映射端口，作为响应的 `port`（agent 不填 host）。
7. 丢弃内存中的私钥，返回响应载荷（含 `deploy_public_key`，供 client 注册 GitHub key）。
8. 若第 4–7 步任一失败：agent 回滚——`rm -f` 该容器（此时尚无 GitHub key，无需清理 GitHub），
   返回 `5xx`。若 agent 成功但 client 侧注册 GitHub key 失败，则由 **client** 调 `DELETE`
   回滚容器（见 §5#3）。

### 6.2 删除流程
> deploy key 的吊销由 **client** 在调用本接口前完成（client 持 token，按 title
> `codespace-<id>` 反查删除，见 §5/§8）；agent 只管容器与工作区目录。
1. 读取容器 `codespace-<id>` 的 labels，取 `codespace.repo`、`codespace.workspace`。
2. `podman rm -f codespace-<id>`。
3. 默认保留工作区目录；`?purge=true` 时用**一次性 helper 容器**删除，仍不需 agent 挂载：
   `run("busybox", command=["rm","-rf","/t"], remove=True,
        mounts=[{"type":"bind","source":<workspace_HOST>/<ws>,"target":"/t"}])`
   （`<ws>` 由 label 推出）。

### 6.3 密钥注入（podman put_archive）
agent 在容器就绪后，通过 podman-py 执行两步：

先修正工作区属主（`user=0`）：
```sh
chown -R <user>:<user> /workspace
```
再把密钥物料写入登录用户的 `~/.ssh/`。私钥内容**不作为命令行参数**（避免出现在进程列表 /
label），也**不落 agent 磁盘**：agent 在**内存**中构造 tar 归档（0600 私钥成员 +
`config` + `authorized_keys`），经 podman 的 `PUT /containers/<c>/archive`
（`container.put_archive`）流式写入 `~/.ssh/`，写入后 `chown -R <user> ~/.ssh` 修正属主。
主 repo 写入的 `~/.ssh/config` 内容为：
```
Host github.com
    HostName github.com
    User git
    IdentityFile ~/.ssh/repo_id_ed25519
    IdentitiesOnly yes
```
**额外只读 repo**：每个额外 repo 各写一把私钥 `~/.ssh/repo_github-<slug>`，并追加一段独立的
`Host github-<slug>`（HostName 仍 github.com、IdentityFile 指向该私钥）到 `~/.ssh/config`；
同时写 `~/.gitconfig` 的 `insteadOf` 重写：
```
[url "git@github-<slug>:owner/dotfiles"]
    insteadOf = git@github.com:owner/dotfiles
```
这样容器内 `git clone git@github.com:owner/dotfiles` 会被透明改写到对应 alias，从而选中该
repo 专属的只读 key（git 取最长匹配前缀，主 repo 的 github.com URL 不受影响）。
> **为何用 put_archive 而非 exec stdin 流**：当前 podman-py（5.x）的 `exec_run` 把 `stdin` /
> `socket` 参数标记为**未实现**（`unused-argument`），无法真正向 exec 的 stdin 流写数据。
> `put_archive`（tar 经 HTTP body 流式上传）保持了同等安全属性——私钥**不作命令行参数、不落
> agent 磁盘、不出现在任何挂载表**——因此作为等价实现被采用。归档在内存中构造，用后即弃。

### 6.4 状态来源（无本地存储）
| 信息 | 存放位置 | 读取方式 |
| --- | --- | --- |
| codespace 元数据（repo/workspace/user/image） | 开发容器 **labels** | `podman ps` 过滤前缀 `codespace-` |
| 端口/运行状态 | podman | podman-py inspect |
| deploy key | GitHub（**client 管理**） | client 用自身 token，按 title `codespace-<id>` 反查 |
| 工作区数据 | 宿主机目录（podman bind） | 由 podman 挂载 |
| GitHub token | **仅存在于 client**，从不经网络/不达 agent | — |

## 7. 工作区持久化（bind mount 目录，无 agent 状态）

- 每个 `(repo, workspace)` 对应宿主机一个固定目录
  `<workspace_root_host>/codespace-<repo-slug>-<workspace>-<hash8>`，以 bind mount 挂到
  容器 `/workspace`。删除容器保留该目录，重建同名 workspace 即复用其中数据。
- **命名与冲突**：`repo-slug` 把 `owner/name` 的 `/` 替换为 `-`，可读性好但可能撞名
  （如 `a/b-c` 与 `a-b/c`）；故追加 `hash8 = sha256("<repo>\0<workspace>")[:8]` 后缀，
  由 `(repo, workspace)` 唯一确定，既稳定可复用又避免串数据。
- 目录属主在容器内由 `podman exec -u 0 chown -R <user> /workspace` 修正（§6.3），
  **不需要 agent 挂载或访问宿主机文件系统**。
- **粒度**：按 `repo + workspace 名`——同一 repo 可用不同 `--workspace` 并行开多个互不
  干扰的 codespace，各自独立持久化。
- **用 bind mount 目录而非 named volume**：便于宿主机侧直接访问/备份；PoP 下卷源为
  宿主机路径字符串，agent 不参与实际挂载。
- 清理：`delete` 默认保留目录；`delete --purge` 用一次性 helper 容器删除（§6.2）。

## 8. 仓库隔离保证

- 注入容器的凭据是 **GitHub Deploy Key**，GitHub 将其严格限定在单个仓库——无法认证到
  任何其它仓库。
- 容器内 `~/.ssh/config` 的 `IdentitiesOnly yes` 强制 git 每个 Host 只用其绑定的 deploy
  key，无法回退到其它身份；额外 repo 各有独立 Host alias + key，互不越权。
- 删除 codespace 时 **client**（持 token）从 GitHub 移除该 codespace 的**每一把** deploy key
  （主 repo + 全部额外 repo），即时吊销访问。
- **主 repo 读写，额外 repo 只读**：主 repo 的 deploy key `read_only: false`（可 push）；
  `extra_repos` 的 deploy key 一律 `read_only: true`（仅拉取，如 dotfiles）。未来可加
  `--read-only` 让主 repo 也只读。

> **cs_id 作单一关联键**：deploy key 的 title 固定 `codespace-<cs_id>`，与容器名/label 里的
> `cs_id` 一致。client 删除时按 title 反查 key（不依赖存下来的 key id），即使本地 ssh config
> 丢失，只要有 `cs_id` + `repo` 即可清干净——三层状态（容器 / GitHub key / 本地块）靠一个
> `cs_id` 对齐（见 §9 一致性）。

## 9. 失败与清理语义

- **两段操作、cs_id 关联、双向回滚**：create 是「agent 建容器」+「client 注册 GitHub key」
  两段跨系统操作，用 `cs_id` 关联（§8）。
  - agent 侧失败（`podman run`/注入）：agent 自行 `rm -f` 容器返回 `5xx`；此时尚无 GitHub
    key，无残留。
  - agent 成功但 client 注册某把 key 失败：client 吊销**已注册的 key**（主 + 额外中已成功的
    那些）+ 调 `DELETE /codespaces/<id>` 回滚容器 + 删本地登录 key，避免孤儿。
- 孤儿回收：`GET /codespaces` 列出存活容器；未来可加 `gc` 命令对账——列出 agent 存活容器的
  `cs_id` 集合 ↔ GitHub 上 `codespace-*` deploy keys，清理无对应容器的孤儿 key。
- client `delete` 尽力幂等：容器（agent 返回 200 even if absent）/ key（按 title 反查，无匹配
  即视为已删）/ config 块缺失均视为已清理，不报错。

## 10. 端到端验证

1. **构建镜像**：先构建 base（`bash images/base/build.sh debian:12`，产出
   `ghcr.io/curoky/devspace:base-debian12`），再 `podman build -t codespace/dev:latest
   codespace/image`（参考镜像 `FROM` 该 base，满足 §3 契约）。
2. **启动 agent**：`bash codespace/agent/run-agent.sh`；`curl http://localhost:8080/codespaces`
   返回 `[]`。
3. **创建**：`python -m codespace.client create --repo owner/name --workspace default
   --token $TOKEN --agent http://<host>:8080 --alias test-cs`。
   - GitHub → Settings → Deploy keys 出现 `codespace-<id>`。
   - `~/.ssh/config` 出现托管块。
4. **登录**：`ssh test-cs` 以登录用户进入容器。
5. **隔离**：容器内 `git clone git@github.com:owner/name.git` 成功且可 push；clone 其它
   仓库失败（无权限）。
6. **持久化**：容器内 `/workspace` 写文件 → `delete`（不 purge）→ 再 `create` 同名
   workspace → 文件仍在。
7. **删除**：`delete --alias test-cs --token $TOKEN`：容器被删、deploy key 消失、
   config 块与本地 key 移除；`--purge` 再删工作区目录。
8. **lint/类型/测试**：`uv run ruff check codespace/ tests/`、`uv run ruff format --check`、
   `uv run mypy codespace/`、`uv run pytest` 全通过；shell 文件 `shfmt` 通过。

## 11. 安全考量与威胁模型（已知并被接受）

> **前提**：本方案明确假定 **client 与 Linux 宿主机均为不可信环境**。以下残余风险
> 已被知悉并接受，v1 **不做**针对性加固（不加 TLS / 鉴权，deploy key 默认读写且无 TTL）。
> 此处如实记录，供后续评估。

- **podman.sock（rootful）== 宿主机 root**：rootful podman service 以 root 运行，agent
  挂载其 socket 即等价拥有宿主机 root；宿主机 root 在开发容器**存活期间**可随时
  `podman exec` 进入或读取容器磁盘，因此**无法阻止**其读取注入的 deploy 私钥与容器内
  数据。这是"在不可信宿主机上运行需要私有 repo 凭据的容器"的固有矛盾。
- **GitHub token 不经网络、不达 agent**：token 仅存在于 client；所有 GitHub 交互（注册 /
  吊销 deploy key）都在 client 本地完成，agent 从不接收 token，明文 HTTP 里也不含 token。
  这较早期「token 经 agent 明文传输」的方案显著收窄了 token 暴露面。
- **deploy 私钥仍会落到不可信宿主机的容器内**：private key 经 agent 注入容器 `~/.ssh/`，
  宿主机 root 存活期内可读；影响面被 deploy key 限制在**单个 repo**，删除时由 client 主动
  吊销。这是上一条无法消除的固有矛盾（凭据必须在容器内才能 clone/push）。
- **agent 无鉴权、明文 HTTP**：任何能访问 agent 端口者都可创建/删除容器（`delete` 仅凭
  `cs_id`）。但 agent 不再持有任何 GitHub 凭据，能造成的最大破坏是操纵容器与工作区目录，
  波及不到 GitHub。
- **deploy key 默认读写、无 TTL**：容器存活期内可用它向该 repo 推送；影响面仅限**单个 repo**。
- **影响面约束**：容器名前缀 `codespace-` 约束 agent 的所有 podman 操作；agent 必须拒绝
  触碰不含该前缀的容器。

## 12. 后续工作

- 可选 `--read-only` 参数 → deploy key `read_only: true`。
- 空闲自动停止 / 容器 TTL 及协调用 `gc` 命令。
- 多用户镜像白名单与配额。

> 注：TLS / bearer 鉴权等传输加固**不在计划内**——威胁模型已在 §11 明确接受 client 与
> 宿主机均不可信的前提。

## 13. 设计决议（review 已定）

以下为 review 中识别、并已与需求方确认的决议：

1. **私钥注入 = put_archive tar 流**（§6.3）：私钥经 podman `PUT .../archive` 的内存 tar
   写入 `~/.ssh/`，不作命令行参数、不落 agent 磁盘。原设计的「exec stdin 流」因当前
   podman-py（5.x）未实现 exec 的 stdin/socket 参数而改用 put_archive，安全属性等价。
2. **就绪判定 = 只等容器 running**（§6.1#6）：注入不依赖 sshd 监听，容器状态达到 `running`
   即注入，带短超时/重试。
3. **去掉 `dir_reused` 字段**：无状态下难可靠判断，价值不大；保持纯 label 方案，不做额外
   目录探测。
4. **工作区目录名加 hash8 后缀**（§7）：`codespace-<repo-slug>-<workspace>-<hash8>`，
   `hash8 = sha256("<repo>\0<workspace>")[:8]`，避免 slug 撞名串数据。
5. **agent 不做鉴权**：与"明文 HTTP、不可信网络已接受"一致；任何能访问 agent 端口者可
   创建/删除容器（`delete` 仅凭 `cs_id`）。但 agent 不持任何 GitHub 凭据，波及不到 GitHub。
   风险已在 §11 记录并接受。
6. **并发**：无状态设计无共享可变状态，随机端口由 podman 分配，并发创建天然安全。
7. **GitHub 交互全收敛到 client、token 不经网络**（§4/§5/§8）：agent 只生成 keypair 并注入
   私钥、返回公钥；client 用自己的 token 注册/吊销 deploy key。以 `cs_id`（= 容器 label = key
   title `codespace-<id>`）为单一关联键，删除按 title 反查，配合双向回滚保证一致性（§9）。
   `image`/`user` 等 caller 侧选择也随之下放到 client 请求，agent 配置仅剩三个宿主机属性。
8. **额外 repo 只读拉取**（§4/§6.3/§8）：`extra_repos`（client 固定配置
   `~/.config/codespace/extra-repos` + `--extra-repo`）为每个额外仓库单独生成一把
   `read_only` deploy key，注入独立 `Host github-<slug>` alias + `~/.gitconfig` `insteadOf`
   重写，使 `git clone git@github.com:owner/x` 透明选中该 repo 专属只读 key。同一公钥不能跨
   repo，故用多把 key；主 repo 仍读写。
