# 控制面（Codespace）约束

`controller/` 是完整的本地单进程控制面，包括配置、Podman transport、生命周期、
Git provider、SSH 投影、FastAPI、原生 Web UI 和测试。入口是：

```bash
uv run python -m controller
```

它通过 system OpenSSH 转发远端 rootful Podman Unix socket，或直接连接已运行的 rootful
Podman Machine；不部署远端 HTTP agent。固定登录 key、SSH 公共配置和 image host key 位于
`controller/assets/ssh/`，启动时原子安装到 `~/.ssh/codespace/`；动态 host 文件只保存端口与
代理路由。

本文是控制面范围、配置、连接机制、生命周期、SSH 投影、Web/HTTP API 与安全边界的事实来源。
仓库整体架构、仓库级常用操作与跨组件契约见仓库根 [`AGENTS.md`](../AGENTS.md)；开发镜像契约见
[`images/dev/AGENTS.md`](../images/dev/AGENTS.md)，host 级共享服务契约见
[`images/sidecar/AGENTS.md`](../images/sidecar/AGENTS.md)。修改控制面配置、生命周期、API 或
host contract 时，必须在同一变更中同步更新本文相关章节。

## 模块职责

本地控制面代码全部放在 `controller/`。不得恢复 `agent/`、顶层兼容模块、生成式 Web 产物或
Node.js 构建链。

| 路径 | 职责 |
| --- | --- |
| `controller/app.py`、`controller/api.py`、`controller/__main__.py` | Web 应用装配、HTTP 路由与入口 |
| `controller/config.py`、`controller/models.py` | 配置与 API model |
| `controller/transport.py`、`controller/ssh.py` | Host 连接、SSH 操作与本地投影 |
| `controller/inventory.py`、`controller/container.py`、`controller/workspace.py` | Podman inventory、容器和 workspace 原语 |
| `controller/service.py`、`controller/dashboard.py`、`controller/operations.py` | 生命周期编排、Dashboard 投影与操作状态 |
| `controller/provider.py` | Git provider deploy key |
| `controller/tools/` | 不依赖 Web UI 的 Codespace 维护 CLI |
| `controller/assets/ssh/` | 固定登录 key、SSH 公共配置和 pinned host key |
| `controller/static/` | FastAPI 直接提供的原生 Web 源码 |
| `controller/tests/` | 按公开模块行为组织的测试 |
| `controller/run.sh` | 本地后台启动器 |

## 常用操作

启动 Codespace 前先按下文「配置」创建 `~/.config/codespace/config.yaml`，再启动控制面：

```bash
uv sync
uv run python -m controller
```

服务只监听 `127.0.0.1:8003`。后台运行使用：

```bash
controller/run.sh
```

清理当前配置仓库中已无对应 environment 的 deploy key，先预览再显式执行：

```bash
uv run python -m controller.tools.cleanup_deploy_keys
uv run python -m controller.tools.cleanup_deploy_keys --no-dry-run
```

清理各 host 上已无对应 environment container 的 workspace：

```bash
uv run python -m controller.tools.cleanup_workspaces
uv run python -m controller.tools.cleanup_workspaces --no-dry-run
```

把顶层 `secrets` 明文注册为各 host 上的 Podman secret，先预览再显式执行：

```bash
uv run python -m controller.tools.sync_secrets
uv run python -m controller.tools.sync_secrets --no-dry-run
```

验证控制面：

```bash
uv run ruff format --check controller
uv run ruff check controller
uv run mypy controller
uv run pytest controller/tests
uv lock --check
```

## 控制面范围

Codespace 是仅监听 localhost 的单进程开发容器控制面，支持远端 rootful Podman host 和
本地 rootful Podman Machine。Python 进程通过 system OpenSSH 转发远端 Podman Unix
socket；Podman Machine 使用 `podman machine inspect` 返回的本地 API socket。

不得增加远端 HTTP agent，也不得改用 podman-py 的 SSH adapter。

FastAPI 同时提供 JSON API 和 `controller/static/` 中的原生 Web 文件。GitHub、GitLab token
只保存在进程内存中；`config.yaml` 的可选 `tokens` 可提供启动值，Web UI 可在运行时覆盖。

## 配置

进程启动时只读取 `~/.config/codespace/config.yaml`。不得增加 TOML、环境变量覆盖、热加载
或备用配置源。

```yaml
default_image: ghcr.io/curoky/devspace:codespace-debian13

container:
  network_mode: host
  cap_add: [NET_RAW, SYS_ADMIN]
  security_opt: [disable, seccomp=unconfined]
  pids_limit: -1
  ulimits:
    memlock: {soft: -1, hard: -1}
  volumes:
    - /etc/krb5.conf:/etc/krb5.conf:ro
  environment:
    HTTP_PROXY: http://proxy:3128
  secrets:
    - supabase_service_key
    - source: supabase_anon
      mode: env
      target: SUPABASE_ANON_KEY

hosts:
  local:
    type: podman-machine
    machine: podman-machine-default
    container:
      network_mode: bridge
  office:
    podman_socket: /tmp/podmanxd.sock
    environment: [HTTP_PROXY, HTTPS_PROXY, NO_PROXY]
  gpu-box:
    container:
      pids_limit: 4096
      devices:
        - nvidia.com/gpu=all
  home:

projects:
  devspace:
    host:
      - name: home
      - name: gpu-box
        platform: linux/amd64
    repo: github:curoky/devspace
    description: Devspace repository
  service-api:
    host:
      - name: office
        platform: linux/arm64
    repo: gitlab:group/service-api
    image: registry.example.com/codespace-api:latest
    container:
      environment:
        NODE_ENV: development
  scratch:
    host:
      - name: home
    type: blank
    open_path: /workspace/notes

tokens:
  github: ghp_xxx
  gitlab: glpat-xxx

secrets:
  supabase_service_key: "eyJhbGci..."
  supabase_anon: "eyJhbGci..."
```

顶层必填字段是 `default_image`、`hosts` 和 `projects`；`container` 可选（省略即全部使用引擎
默认）。登录容器所用的固定 keypair 位于 `controller/assets/ssh/`，控制面启动时把私钥安装到
`~/.ssh/codespace/login_key`，无需配置；对应公钥已烤进开发镜像的 `authorized_keys`。
`hosts` 是以 host alias 为 key 的映射，值为该 host 的连接设置；host 值可以留空（等价默认
SSH host）。每个 project 用 `host` 声明可启动的 host 列表（同一 repo 只出现一次），列表每项是
`{name, platform?}`：`name` 引用已配置的 host alias，可选 `platform` 是该 host 上的目标平台。
project 按 `type` 决定 repo 相关字段，可选
`description`、`image`、`open_path`、`published_ports` 和 `container`。其他规则如下：

- `type` 默认 `repo`，也可设为 `blank`。`repo` 类型必须配置 `repo`（因此带 `provider`）；
  `blank` 类型禁止配置 `repo` 和 `provider`。
- `repo` 写成 `<provider>:<owner>/<name>`，`provider` 只能是 `github` 或 `gitlab`。
- `open_path` 可选，必须是绝对路径；未设置时 `repo` 类型默认打开仓库目录，`blank` 类型默认
  打开挂载点 `/workspace`。编辑器 deep link 按此路径打开。
- 每个 host 条目的 `platform` 只能是 `linux/amd64` 或 `linux/arm64`；省略时使用该 host 原生平台。
- `published_ports` 可选，是要发布到宿主机的端口列表，每项写成 `"<remote>"`（local=remote）
  或 `"<local>:<remote>"`，端口取值 1-65535，同一 project 内 local 端口不得重复。只有解析后
  `container.network_mode` 为 `bridge` 的 project 可配置 `published_ports`（bridge 容器有独立
  netns 才能发布端口），解析为 `host` 时配置 `published_ports` 直接拒绝。改动
  `published_ports` 需重建实例才生效。
- `hosts.<host>.type` 默认是 `ssh`，也可设为 `podman-machine`。
- SSH host 可配置绝对路径 `podman_socket`，默认 `/run/podman/podman.sock`，不得配置
  `machine`。
- SSH host 可配置 `environment`，值为需要从该 host 的非交互 SSH 登录环境继承到开发容器的
  变量名列表。变量名必须匹配 `^[A-Za-z_][A-Za-z0-9_]*$`、不得重复，也不得包含控制面保留键
  `SSHD_PORT`、`SSHD_BIND`。控制面在每次创建实例时读取这些变量；任一变量未导出就终止创建，
  不传空值或沿用旧值。`container.environment` 仍用于显式固定值，两者不得包含同名变量。
- Podman Machine host 必须配置 `machine`，不得配置 `podman_socket`。
- Podman Machine host 不支持 `environment`；该能力只适用于 Linux SSH host。
- `tokens` 中的 `github`、`gitlab` 是可选的非空字符串。
- 顶层 `secrets` 是可选映射，key 为 secret 名、value 为明文密钥值，供带外 CLI
  `sync_secrets` 在各 host 上注册 Podman secret（见「Secret 同步」）。它只服务于该 CLI，
  控制面进程本身不消费这些明文，运行时只按 `container.secrets` 的名字引用已注册 secret。明文
  写进 `config.yaml` 属于运维取舍：配置文件必须限制权限并排除版本控制。
- 顶层 `container` 是可选块，承载所有非身份的容器 run flag，采用 Docker Compose service 的
  字段名与语法子集（解析实现独立在 `controller/compose/` 子包中，只做强类型化，不含控制面知识），
  控制面自身不保留任何隐式默认值。所有字段（`network_mode`、`cap_add`、`security_opt`、
  `pids_limit`、`ulimits`、`volumes`、`environment`、`secrets`、`devices`、`shm_size`，对应
  `--network`、`--cap-add`、`--security-opt`、`--pids-limit`、`--ulimit`、`--secret`、`--device`、
  `--shm-size`）全部可选，
  未设置等价于 Compose 语义下的「引擎默认」：在 runtime 边界处集合归一为空、`pids_limit` 和
  `shm_size` 仅在设置时才转发给 `podman run`。
  `network_mode` 只能是 `host` 或 `bridge`，原样转发给 `--network`：`host` 让容器共享 host netns；
  `bridge` 让容器获得独立 netns，sshd 注入 `SSHD_BIND=0.0.0.0` 并发布 SSH 端口和业务端口。虽然
  compose 语义下 `network_mode` 可省略，但控制面要求**每个 project 分层解析后必须有确定的
  `network_mode`**（缺失即在加载时 fail-fast），因此实践中通常在顶层 `container` 设一次全局默认。
  `ulimits` 是以限制名为 key 的映射，值为 `{soft, hard}` 或裸整数（等价 soft=hard）。`volumes`
  支持 Compose 短语法 `source:target[:ro|rw]` 或长语法
  `{type: bind, source, target, read_only}`；只支持 `type: bind`，`source`/`target` 必须是绝对
  路径，`read_only` 默认 `false`。`/workspace` 和 `/upload` 是控制面保留的 mount tree；
  `volumes` 的 target 不得与任一路径相同，也不得是其父目录或子目录。`devices` 是原样转发给
  `--device` 的字符串列表，GPU 访问用 CDI 设备名表达（如 `nvidia.com/gpu=all`），要求该 host
  已安装 NVIDIA 驱动与 CDI 规范文件。
  `shm_size` 是原样转发给 `--shm-size` 的非空字符串，采用 podman 认的格式（纯字节整数字符串或
  单字母后缀 `b`/`k`/`m`/`g`，如 `100g`），控制面不做归一。
  `container.environment` 是显式透传给容器的固定环境变量，支持映射或
  `["KEY=value"]` 列表短语法，禁止使用控制面派生的保留键 `SSHD_PORT`、`SSHD_BIND`。这些值原样
  转发给 `podman run`，控制面不做任何转换。
  `secrets` 引用 host 上已用 `podman secret create` 预注册的 Podman secret，控制面只按名字引用、
  绝不持有明文。每项支持裸字符串短语法（等价 `{source: <name>, mode: mount}`）或长语法
  `{source, mode, target?, uid?, gid?, file_mode?}`。`mode: mount`（默认）把 secret 以文件暴露，
  `target` 是容器内绝对路径、省略时默认 `/run/secrets/<source>`，`uid`/`gid` 默认容器用户
  `5230:5230`、`file_mode` 默认 `0o400`，保证只有 `x` 可读；`mode: env` 把 secret 注入为
  `target` 命名的环境变量，此时必须给出匹配 `^[A-Za-z_][A-Za-z0-9_]*$` 的 `target`，且禁止设置
  `uid`/`gid`/`file_mode`。`mode: env` 的 `target` 与 `container.environment`、`hosts.<host>.environment`
  继承变量共享同一命名空间，不得重名，也不得使用保留键 `SSHD_PORT`、`SSHD_BIND`；`mode: mount`
  的 `target` 不得与保留 mount tree `/workspace`、`/upload` 相同或互为父子路径。
- `hosts.<host>.container` 和 `projects.<project>.container` 是可选覆盖，与顶层 `container`
  共用同一个全可选模型。已设置的 key 整体替换对应的下层值（浅层 key 级替换，非深合并），未设置
  （`None`）的 key 继承下层值。优先级 `project > host > global`。覆盖块的 `environment` 同样禁止
  保留键。
- 拒绝未知字段。
- Project 和 instance ID 匹配 `^[a-z0-9][a-z0-9-]{0,31}$`。
- Host alias 匹配 `^[a-z0-9][a-z0-9.-]{0,62}$`。
- `hosts` 至少包含一个 host；project 的 `host` 列表至少一项且 host name 不得重复，每个
  name 只能引用已配置的 host。
- Project 未配置 `image` 时使用 `default_image`。

## Host 契约

SSH host ID 必须是本地 `~/.ssh/config` 中可访问 rootful Podman 的现有 alias。workspace
目录以普通 SSH 登录用户身份创建（`mkdir -p`），无需免密 `sudo`；容器启动时由镜像内
`workspace-init` s6 oneshot 将挂载的 `/workspace` 归属到 `5230:5230`（rootful Podman
直接透传 host 所有权）。身份文件、跳板机和 host key policy 由 system OpenSSH 管理。

Podman Machine host ID 是 Codespace 内的逻辑名称；对应 machine 必须已存在、正在运行且
使用 rootful 模式。

每个 host 必须提供：

- rootful Podman socket；SSH host 默认是 `/run/podman/podman.sock`，Podman Machine
  通过 `podman machine inspect` 获取 API socket 和 SSH identity；
- SSH 登录用户的可写 home；workspace root 是绝对路径化后的 `~/codespace`；
- GNU `env`（支持 `-0`），用于读取 `hosts.<host>.environment` 声明且已在非交互 SSH 会话中
  导出的变量；
- `find`（支持 `-mindepth`、`-maxdepth` 和 `-print0`），用于维护工具列出 workspace；
- 允许开发镜像内 root 将挂载的 `/workspace` `chown` 为 `5230:5230`；
- 为 environment SSH 保留的端口范围 `20000-29999`；
- 一个 host 级 sidecar；
- 满足 [`images/dev/AGENTS.md`](../images/dev/AGENTS.md) 契约的开发镜像。

非原生平台依赖 host 已注册持久化 `binfmt_misc` interpreter，通常为 QEMU user-static。
Codespace 只选择平台，不安装或管理模拟器。

开发镜像必须提供的完整契约见 [`images/dev/AGENTS.md`](../images/dev/AGENTS.md)。Sidecar 镜像和
网络细节见 [`images/sidecar/AGENTS.md`](../images/sidecar/AGENTS.md)，它必须独立于 project 和
instance 资源。

## 资源标识

Environment 的 container name、本地 SSH alias 和 deploy-key title 共用确定性 ID：

```text
codespace-<host>-<project>-<instance>
```

Host workspace 为 `<login-home>/codespace/<project>/<instance>`，挂载到容器
`/workspace`。SSH 端口计算公式是：

```text
20000 + int(sha256(environment_id)[:4], 16) % 10000
```

若与同一 host 上其他受管 environment 冲突，直接拒绝，不探测替代端口。

Podman inventory 是唯一事实来源。Environment container 必须具有
`codespace.managed=true`，以及完整的 project、instance、type、image、platform、SSH port
label。`codespace.type` 只能是 `repo` 或 `blank`：`repo` 类型额外携带 `codespace.repo`
和 `codespace.provider`，`blank` 类型不得携带这两个 label。未选择平台时 platform label 是
`native`。缺失、格式错误、与配置 `type` 不符或引用未知 project 的 label 都是 inventory
error，不得推断默认值。

Sidecar 是 host 级单例，不得复用 environment 的 ID、workspace、deploy key 或 SSH 投影。

## 连接机制

每个 host 维护一个可复用的 Podman client。SSH host 另维护一个 system SSH 进程：

```text
ssh -N -o ExitOnForwardFailure=yes -o StreamLocalBindUnlink=yes \
  -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -L <local.sock>:<host podman_socket> <host>
```

转发目标是解析后的 `podman_socket`。本地 socket 位于权限为 `0700` 的进程私有 runtime
目录。SSH keepalive 必须让失效 tunnel 自动退出，Podman 调用必须有超时；进程退出后重建
tunnel，应用关闭时释放 Podman client 和 SSH 子进程。Podman client 和常规 container exec
的读超时均为 60 秒；image pull 通过同一 Unix socket 上的临时 Podman client 使用 15 分钟
流数据间隔超时，repository clone 的 exec start 也单独使用 15 分钟读超时，不得因此放宽
Dashboard inventory 等普通 API 的故障边界。临时 pull client 必须在成功或失败后关闭。

Podman Machine 连接从 `podman machine inspect` 读取 API socket、SSH 端口和 identity；
拒绝已停止或 rootless machine。Dashboard 并发查询各 host，一个离线 host 不得阻塞其他
host。

## 环境生命周期

控制面启动时必须先校验 `controller/assets/ssh/` 中的 `config`、`known_hosts` 和 `login_key`，
再以 `0600` 原子安装到 `~/.ssh/codespace/`；任一 asset 缺失立即 fail-fast。该初始化不属于
单个 environment 的创建流程。

创建顺序不可调整：

1. 校验 inventory、token、重复 ID 和 SSH 端口冲突。
2. 若 `hosts.<host>.environment` 非空，通过该 host 的非交互 SSH 登录环境读取所有声明的变量；
   任一变量未导出即失败。该步骤只保存本次创建所需的内存快照。
3. 在内存中生成 environment deploy key。
4. 按所选 host 条目的平台拉取镜像；未配置时使用 host 原生平台。
5. 以 SSH 登录用户身份创建 host workspace 目录（`mkdir -p`，无需 `sudo`）。
6. 按解析后的 `container` 配置创建带完整 label 的 container：非身份 run flag（`network_mode`、
   `cap_add`、`security_opt`、`pids_limit`、`ulimits`、`devices`、额外 `volumes` 和
   `container.environment`）由 global/host/project 分层解析后原样透传，控制面不补默认；
   第 2 步读取的 host 环境快照同时注入且禁止与显式 `container.environment` 重名。GPU 通过
   `container.devices` 里的 CDI 设备名（如 `nvidia.com/gpu=all`）表达。`container.secrets`
   在此逐个校验对应 Podman secret 已在该 host 注册，缺失即 fail-fast、不创建 container；
   `mode: mount` 转发为 `--secret`（默认归属 `5230:5230`、mode `0o400`），`mode: env`
   把 secret 值注入为目标环境变量，与继承和显式环境变量共享命名空间且不得重名。解析后的
   `container.network_mode` 原样转发给 `--network`；`bridge` 模式下
   注入 `SSHD_BIND=0.0.0.0`，发布 SSH 端口到 loopback，并发布 project `published_ports`
   声明的业务端口。
7. 镜像内 `workspace-init` 先将挂载的 `/workspace` `chown` 为 `5230:5230`，之后才允许
   `sshd` 和 `home-init` 启动。
8. `repo` 类型只把内存中生成的私钥整体写入镜像预创建的
   `/home/x/.ssh/repo_id_ed25519`，再将该文件归属设为 `5230:5230`。Provider SSH config
   和 pinned `known_hosts` 已由镜像安装，控制面不得生成或覆盖。登录公钥已烤进开发镜像的
   `authorized_keys`，控制面只用仓库内固定的登录私钥登录。`blank` 类型不注入任何凭据。
9. 通过生成的 route 完成真实 SSH 登录验证。
10. 将 provider 上同名 deploy key 替换为一个可写 key。
11. 保留 `HEAD` 有效的现有 Git checkout，以及带
    `.git/codespace-empty-repository` 标记的已成功空仓库 checkout。存在 `.git` 但两项均不满足
    时视为中断 clone 的残留并清理；目标路径存在但不是 Git checkout 时拒绝覆盖。新 clone 先清理
    `<target>.codespace-clone` 临时目录，再以 15 分钟 exec 读超时执行
    `git clone --depth=1`，成功后原子移动到目标路径；成功 clone 的空仓库写入上述标记。
12. 原子更新 host SSH 投影。

注册 deploy key 前失败时，回滚 container 但保留 workspace。注册后失败时，必须先撤销
key；撤销失败则停止并保留带 label 的 container，待 token 恢复后重试正常删除。

`blank` 类型 project 跳过与仓库相关的步骤：不生成或注册 deploy key（步骤 3、10），不 clone
repository（步骤 11），创建与删除均不需要 provider token；其余步骤与 `repo` 类型一致。由于
没有 clone 产生的 checkout 目录，`blank` 类型在容器内以容器用户身份 `mkdir -p` 其 `open_path`
（默认挂载点 `/workspace`），保证编辑器打开的是一个已存在的目录。

删除 `repo` 类型需要 provider token，并在任何远端变更前撤销所有匹配 deploy key。Key 已不
存在视为幂等成功。`blank` 类型没有 provider 状态，直接进入 container 与 workspace 处理。
`purge=false` 只删除 container；`purge=true` 先停止 container，再依据其 image label 清理
workspace，最后删除 container。Provider 失败时不得改变 container 和 workspace。

删除 `repo` 类型时分两阶段。`force=false` 只在容器内的 checkout 目录检测未 push 提交
（`git log --branches --not --remotes`）和未提交/未跟踪改动（`git status --porcelain`），
不做任何 container/workspace/provider 变更，返回 `{deleted, workspace_removed, state}`，
其中 `state` 含 `unpushed`、`uncommitted`、`detail`。WebUI 先以 `force=false` 打开 block
弹窗展示检测结果，用户确认后再以 `force=true` 真正删除（此时执行撤销 deploy key、按 purge
清理 workspace、删除 container）。Git 检测仅允许在 `running` container 内执行，不得为预检
启动已退出或停止的 container；WebUI 根据 Dashboard status 直接显示未检测警告并允许用户确认，
直接调用 `force=false` API 时则立即返回错误。`blank` 类型无 checkout，`state` 恒为空。检测只
发生在删除路径，dashboard 不受影响。

## Deploy key 清理

未使用 deploy key 由独立 CLI 清理，不增加 Web UI 或 HTTP API：

```bash
# 只预览
uv run python -m controller.tools.cleanup_deploy_keys

# 执行删除
uv run python -m controller.tools.cleanup_deploy_keys --no-dry-run
```

`controller/tools/cleanup_deploy_keys.py` 固定读取 `~/.config/codespace/config.yaml`，并发列出其中
全部 GitHub/GitLab 仓库的 deploy key，同时读取 host inventory 判断 key 是否仍有对应
container。输出固定为 `Repository`、`Deploy key`、`In use` 三列表格；`In use` 取值为
`yes`、`no`、`unknown` 或 `unmanaged`。host 不可用时对应 key 为 `unknown`，非
`codespace-` key 为 `unmanaged`，二者都不得删除。默认 dry-run，只有 `--no-dry-run` 删除
`In use=no` 的 key。仓库或 host 查询失败时输出 warning，不影响其他并发查询。

GitHub 不提供账号级 deploy key 枚举 API，因此已从配置移除的仓库无法由该 CLI 自动发现；
需要先保留或临时恢复对应 project 配置再清理。

## Workspace 清理

容器删除后遗留的 workspace 由独立 CLI 清理：

```bash
# 只预览
uv run python -m controller.tools.cleanup_workspaces

# 执行删除
uv run python -m controller.tools.cleanup_workspaces --no-dry-run
```

`controller/tools/cleanup_workspaces.py` 并发读取每个 host 的 Podman inventory，并列出
`<login-home>/codespace/<project>/<instance>` 两层目录。输出固定为 `Host`、`Workspace`、
`In use` 三列表格；存在对应受管 container 时为 `yes`，符合 project/instance ID 规则但无
container 时为 `no`，其他目录为 `unmanaged`。host 不可用或 inventory 损坏时输出 warning
并跳过该 host。

默认 dry-run，只有 `--no-dry-run` 删除 `In use=no` 的目录。删除操作按 host 并发、同一 host
内串行执行，使用 `default_image` 启动 root helper container，并只将 workspace root bind mount
给 helper；删除目标必须是 workspace root 的严格子路径。`unmanaged` 目录不得删除。

## Secret 同步

控制面创建实例时只校验 `container.secrets` 引用的 Podman secret 已存在，从不创建 secret。
把顶层 `secrets` 明文注册到各 host 由独立带外 CLI 完成：

```bash
# 只预览
uv run python -m controller.tools.sync_secrets

# 执行创建/替换
uv run python -m controller.tools.sync_secrets --no-dry-run
```

`controller/tools/sync_secrets.py` 读取顶层 `secrets` 明文映射，把其中**每个** secret 注册到
`hosts` 里的**每个** host，不做引用分析。输出固定为 `Host`、`Secret`、`Action` 三列表格；
`Action` 为 `create`（host 上不存在）或 `replace`（已存在，将删后重建让 config 值生效）。默认
dry-run，只有 `--no-dry-run` 才 `podman secret rm` + `create`。host 查询失败输出 warning，不
影响其他并发 host。顶层 `secrets` 为空时直接空转、不建立连接。

## SSH 投影

`~/.ssh/config` 中只增加一个 include：

```sshconfig
Include ~/.ssh/codespace/config
```

Codespace 完全管理 `~/.ssh/codespace/config`、`login_key`、`known_hosts/` 和
`hosts/*.conf`。固定文件从 `controller/assets/ssh/` 原子安装；只有 inventory 成功后才能重写
host 投影，host 离线时保留最后版本，从 YAML 移除后才删除。

静态 `config` 通过 `Host codespace-*` 统一声明 `HostName 127.0.0.1`、用户 `x`、managed
`IdentityFile` 和 host-key policy；动态 `hosts/*.conf` 每个 environment 只声明确定性端口和
`ProxyJump`/`ProxyCommand`。登录公钥已烤进开发镜像的 `authorized_keys`，控制面不再生成或
注入登录公钥。所有 environment 共用镜像内固定的 sshd ed25519 host key，通过
`HostKeyAlias codespace` 指向单个 pinned `~/.ssh/codespace/known_hosts/codespace`，并用
`StrictHostKeyChecking yes` 做真实校验。该 known-hosts asset 必须与镜像
`images/dev/rootfs/etc/ssh/ssh_host_ed25519_key.pub` 一致；改镜像 host key 必须同步更新它。
SSH host 使用 `ProxyJump <host>`；Podman Machine 使用由 inspect 结果构造的专用
`ProxyCommand`，其 `machine-<host>` known-hosts 校验的是 VM 自身 host key（与镜像 host key
无关），保持 accept-new。不得解析或合并历史 SSH block。

## Web 契约

前台启动：

```bash
uv run python -m controller
```

后台启动并将日志保存在仓库内：

```bash
controller/run.sh
```

应用固定使用单 worker 并监听 `127.0.0.1:8003`。只保留以下 API：

- `GET /api/dashboard`
- `PUT /api/tokens/{provider}`
- `POST /api/projects/{project}/instances`（body 含 `host` 和 `instance`）
- `DELETE /api/projects/{project}/hosts/{host}/operations/{instance}`
- `DELETE /api/projects/{project}/hosts/{host}/instances/{instance}?purge=true|false&force=true|false`

错误格式固定为 `{"error": "..."}`。创建请求 body 用 `host` 显式选择 project 声明的某个 host；
`host` 必须在 project 的 `host` 列表内，否则拒绝。`DELETE` 路径带 `host`，因为同名 instance
可分布在不同 host（identity 由 host+project+instance 共同决定）。`DELETE` 成功返回
`{deleted, workspace_removed, state}`，
`force=false` 时 `deleted=false` 且 `state` 携带 git 检测结果。Dashboard response 是浏览器
的唯一事实来源；每个 project summary 携带其 `hosts` 列表（各含 `name` 和可选 `platform`），
Web UI 为每个 environment 显示其中的完整 `ssh_command`；点击命令通过
Clipboard API 复制，并显示短暂的成功反馈。创建对话框先选 host（Quick Create 用列表首个
host），只在 create operation 处于 queued 或 running 时轮询。失败的 create operation 保留
错误信息，并提供关闭按钮调用 operation `DELETE` API 清理；该 API 只允许清理 `failed` 状态，
对不存在的 operation 幂等返回 `{"dismissed": false}`，不得隐藏 queued 或 running operation。
不得增加 SSE、前端 optimistic state、OpenAPI 页面或独立 host/port 配置。

## 安全边界

- Rootful Podman socket 等同于 host root 权限。
- 必须保留 system OpenSSH host-key verification。
- Provider token 只能发送给选定 Git provider，不得返回或写入日志。配置文件中的 token
  是明文，只能本地保存、限制权限并排除版本控制；控制面不得回写。
- `controller/__init__.py` 在导入时调用 `truststore.inject_into_ssl()`，让 HTTPS provider 访问
  复用操作系统信任库（macOS Keychain / Linux 系统 CA），以信任公司 TLS 检查网关重签发的
  证书；不得改回仅信任 certifi，也不得为绕过校验关闭 TLS 验证。
- Deploy private key 只能存在于对应开发容器。
- 应用级密钥（如 Supabase key）由 host operator 用 `podman secret create` 预注册，控制面只按
  名字引用、绝不持有明文，也不得回写或落盘。secret 明文只在容器内出现：`mode: mount` 默认以
  `0o400`、归属 `5230:5230` 暴露文件，只有 `x` 可读；`mode: env` 注入的值同样只存在于容器
  进程环境。日志中不得出现 secret 明文。顶层 `secrets` 块是唯一例外的明文来源，仅供带外
  `sync_secrets` CLI 使用；一旦启用，`config.yaml` 就含明文密钥，必须限制文件权限并排除
  版本控制，控制面运行时进程仍不读取这些值。
- 开发容器访问 GitHub/GitLab 必须使用镜像内 pinned `known_hosts` 做严格 host key 校验。
- 登录 keypair 是固定的、提交进仓库的共享凭据，公钥烤进开发镜像。该方案仅面向内网、且配置不
  存放 IP/port，威胁模型下私钥泄露无实质影响；不得用它保护任何对外可达的 host。
- Web 应用不得远程暴露，也不得增加 worker。
- Sidecar 共享服务只能通过 host loopback 暴露；bridge container 只有在 host publish
  限制为 `127.0.0.1` 时，内部才可绑定所有接口。

## 变更规则

- 修改 Codespace 配置、生命周期、API、host contract：同步更新本文相关章节；涉及 sidecar 时
  还要更新 [`images/sidecar/AGENTS.md`](../images/sidecar/AGENTS.md)，涉及开发镜像时还要更新
  [`images/dev/AGENTS.md`](../images/dev/AGENTS.md)。
- 本地控制面的 Python、静态资源、启动器和测试全部保留在 `controller/`。
- 优先添加针对受影响模块的聚焦测试，不恢复兼容路径。
- 不恢复已删除的兼容目录、远端 Python agent 或 Node Web 构建链。
