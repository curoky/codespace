# 控制面（Codespace）约束

`controller/` 是完整的本地单进程控制面，包括配置、Podman transport、生命周期、Git provider、
SSH 投影、FastAPI、原生 Web UI 和测试，入口 `uv run python -m controller`。它通过 system OpenSSH
转发远端 rootful Podman Unix socket，或直连已运行的 rootful Podman Machine，不部署远端 HTTP agent。

本文是控制面范围、配置、连接机制、生命周期、SSH 投影、Web/HTTP API 与安全边界的事实来源。整体架构与
跨组件契约见仓库根 [`AGENTS.md`](../AGENTS.md)；开发镜像契约见 [`images/dev/AGENTS.md`](../images/dev/AGENTS.md)，
host 级共享服务见 [`images/sidecar/AGENTS.md`](../images/sidecar/AGENTS.md)。修改控制面配置、生命周期、
API 或 host contract 时必须同步更新本文相关章节。

## 模块职责

本地控制面代码全放 `controller/`。不得恢复 `agent/`、顶层兼容模块、生成式 Web 产物或 Node.js 构建链。

| 路径 | 职责 |
| --- | --- |
| `controller/app.py`、`api.py`、`__main__.py` | Web 应用装配、HTTP 路由与入口 |
| `controller/config.py`、`models.py` | 配置与 API model |
| `controller/runtime/` | 与 codespace 无关的通用底层设施：`engine.py`（Podman image/container/exec 原语）、`transport.py`（Podman Host 连接）、`remote.py`（通用 SSH 远程命令与本地原子文件写）、`compose/`（Compose 语法子集解析）。**不得** import 任何 codespace 业务模块 |
| `controller/ssh.py` | codespace SSH 投影与登录 probe（`~/.ssh/codespace/` 布局、`codespace-*` 别名），底层远程/文件操作调 `controller/runtime/remote.py` |
| `controller/inventory.py`、`container.py`、`workspace.py` | Podman inventory、codespace 容器语义（在 `runtime/engine.py` 之上注入 label/workspace mount/secret 默认）和 workspace 原语 |
| `controller/service.py`、`dashboard.py`、`operations.py` | 生命周期编排、Dashboard 投影与操作状态 |
| `controller/provider.py` | Git provider deploy key |
| `controller/tools/` | 不依赖 Web UI 的维护 CLI |
| `controller/assets/ssh/` | 固定登录 key、SSH 公共配置和 pinned host key |
| `controller/static/` | FastAPI 直接提供的原生 Web 源码 |
| `controller/tests/` | 按公开模块行为组织的测试 |
| `controller/run.sh` | 本地后台启动器 |

## 常用操作

先按「配置」创建 `~/.config/codespace/config.yaml`，再启动控制面（只监听 `127.0.0.1:8003`）：

```bash
uv sync
uv run python -m controller       # 前台
controller/run.sh                 # 后台，日志存仓库内

# 维护 CLI（默认 dry-run，加 --no-dry-run 才写）：详见各自章节
uv run python -m controller.tools.cleanup_deploy_keys [--no-dry-run]
uv run python -m controller.tools.cleanup_workspaces  [--no-dry-run]
uv run python -m controller.tools.sync_secrets        [--no-dry-run]
uv run python -m controller.tools.deploy_sidecar      [--no-dry-run]

# 验证
uv run ruff format --check controller
uv run ruff check controller
uv run mypy controller
uv run pytest controller/tests
uv lock --check
```

## 控制面范围

Codespace 仅监听 localhost，支持远端 rootful Podman host 和本地 rootful Podman Machine；不得增加远端
HTTP agent，也不得改用 podman-py 的 SSH adapter。FastAPI 同时提供 JSON API 和 `controller/static/` 的
原生 Web 文件。GitHub、GitLab token 只存进程内存；`config.yaml` 的可选 `tokens` 提供启动值，Web UI 可运行时覆盖。

## 配置

进程启动时只读 `~/.config/codespace/config.yaml`。不得增加 TOML、环境变量覆盖、热加载或备用配置源。

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
  abbie:
    host:
      - name: home
    repo: git:git@curoky:devspace

tokens:
  github: ghp_xxx
  gitlab: glpat-xxx

secrets:
  supabase_service_key: "eyJhbGci..."
  supabase_anon: "eyJhbGci..."
```

顶层必填 `default_image`、`hosts`、`projects`；`container` 可选（省略即全用引擎默认）。登录 keypair 位于
`controller/assets/ssh/`，启动时私钥装到 `~/.ssh/codespace/login_key`，公钥已烤进镜像 `authorized_keys`，
无需配置。`hosts` 以 host alias 为 key，值为连接设置，可留空（等价默认 SSH host）。每个 project 用 `host`
声明可启动 host 列表（同一 repo 只出现一次），列表每项 `{name, platform?}`。project 按 `type` 决定 repo
相关字段，可选 `description`、`image`、`open_path`、`clone_path`、`published_ports`、`container`。规则：

- `type` 默认 `repo`，可设 `blank` 或 `git`。`repo` 必须配 `repo`（因此带 `provider`）；`git` 必须配 `git_url`、
  禁止配 `repo`/`provider`；`blank` 禁止配 `repo`/`provider`/`git_url`。
- `repo` 写成 `<provider>:<owner>/<name>`，`provider` 只能 `github` 或 `gitlab`。也可写成 `git:<完整 git+ssh URL>`
  作为 `git_url` 的简写（自动置 `type: git`），如 `repo: git:git@curoky:devspace`。
- `git` 类型直接 clone 原始 `git@host:owner/name.git`（或 `ssh://` 形式）URL，不生成或注册 deploy key，凭据与
  host key 校验完全依赖镜像内 SSH 契约（GSSAPI/Kerberos 或运维预置的 `known_hosts`）；控制面不为其管理任何凭据。
- `clone_path` 可选（仅 `repo`/`git`，`blank` 禁止配），必须是 `/workspace` 下的严格子路径绝对路径，指定 clone
  的 checkout 目录；未设时 `repo` 默认 `/workspace/<name>`、`git` 从 URL 末段派生。目标父目录若不存在，clone 前
  以容器用户 `mkdir -p` 补齐。
- `open_path` 可选、必须绝对路径；未设时优先回退到 `clone_path`，其次 `repo`/`git` 默认打开仓库目录（`git` 从
  URL 末段派生），`blank` 默认打开 `/workspace`。编辑器 deep link 按此路径打开。
- 每个 host 条目 `platform` 只能 `linux/amd64` 或 `linux/arm64`；省略用该 host 原生平台。
- `published_ports` 可选，每项 `"<remote>"`（local=remote）或 `"<local>:<remote>"`，取值 1-65535，同一
  project 内 local 端口不得重复。只有解析后 `container.network_mode` 为 `bridge` 的 project 可配置
  （bridge 有独立 netns 才能发布端口），解析为 `host` 时配置直接拒绝。改动需重建实例才生效。
- `hosts.<host>.type` 默认 `ssh`，可设 `podman-machine`。SSH host 可配绝对路径 `podman_socket`（默认
  `/run/podman/podman.sock`）、不得配 `machine`；Podman Machine host 必须配 `machine`、不得配 `podman_socket`。
- SSH host 可配 `environment`（需从非交互 SSH 登录环境继承到容器的变量名列表）：变量名匹配
  `^[A-Za-z_][A-Za-z0-9_]*$`、不得重复、不得含保留键 `SSHD_PORT`/`SSHD_BIND`。控制面每次创建实例时读取，
  任一未导出即终止创建，不传空值或沿用旧值。`container.environment` 用于显式固定值，两者不得同名。Podman
  Machine host 不支持 `environment`。
- `tokens.github`/`gitlab` 是可选非空字符串。
- 顶层 `secrets` 是可选映射（key 为 secret 名、value 为明文），供带外 CLI `sync_secrets` 在各 host 注册
  Podman secret（见「Secret 同步」）。控制面进程本身不消费这些明文，运行时只按 `container.secrets` 名字
  引用已注册 secret。明文写进 `config.yaml` 须限制权限并排除版本控制。
- 顶层 `container` 是可选块，承载所有非身份容器 run flag，采用 Docker Compose service 字段名与语法子集
  （解析独立在 `controller/runtime/compose/` 子包，只做强类型化、不含控制面知识），控制面不保留隐式默认。所有字段
  （`network_mode`、`cap_add`、`security_opt`、`pids_limit`、`ulimits`、`volumes`、`environment`、`secrets`、
  `devices`、`shm_size`，对应 `--network`、`--cap-add`、`--security-opt`、`--pids-limit`、`--ulimit`、
  `--secret`、`--device`、`--shm-size`）全部可选，未设置等价 Compose 语义的「引擎默认」：集合归一为空、
  `pids_limit`/`shm_size` 仅在设置时才转发。
  - `network_mode` 只能 `host` 或 `bridge`：`host` 共享 host netns；`bridge` 获独立 netns，sshd 注入
    `SSHD_BIND=0.0.0.0` 并发布 SSH 与业务端口。虽然 compose 可省略，但控制面要求**每个 project 分层解析后
    必须有确定的 `network_mode`**（缺失即加载时 fail-fast），故通常在顶层 `container` 设一次全局默认。
  - `ulimits` 值为 `{soft, hard}` 或裸整数（soft=hard）。
  - `volumes` 支持短语法 `source:target[:ro|rw]` 或长语法 `{type: bind, source, target, read_only}`；只支持
    `type: bind`，`source`/`target` 必须绝对路径，`read_only` 默认 `false`。target 不得与保留 mount tree
    `/workspace`、`/upload` 相同或互为父子路径。
  - `devices` 原样转发给 `--device`，GPU 用 CDI 设备名（如 `nvidia.com/gpu=all`），要求该 host 已装 NVIDIA
    驱动与 CDI 规范文件。
  - `shm_size` 原样转发给 `--shm-size`（podman 认的格式），控制面不做归一。
  - `environment` 支持映射或 `["KEY=value"]` 列表短语法，禁用保留键 `SSHD_PORT`/`SSHD_BIND`，原样转发。
  - `secrets` 引用 host 上已 `podman secret create` 预注册的 secret，控制面只按名字引用、绝不持有明文。每项
    支持裸字符串（等价 `{source: <name>, mode: mount}`）或长语法 `{source, mode, target?, uid?, gid?,
    file_mode?}`。`mode: mount`（默认）把 secret 以文件暴露，`target` 是容器内绝对路径（省略默认
    `/run/secrets/<source>`），`uid`/`gid` 默认 `5230:5230`、`file_mode` 默认 `0o400`（只有 `x` 可读）；
    `mode: env` 注入为 `target` 命名的环境变量，必须给出匹配 `^[A-Za-z_][A-Za-z0-9_]*$` 的 `target` 且禁设
    `uid`/`gid`/`file_mode`。`mode: env` 的 `target` 与 `container.environment`、`hosts.<host>.environment`
    继承变量共享命名空间、不得重名、不得用保留键；`mode: mount` 的 `target` 不得与保留 mount tree 相同或互为父子。
- `hosts.<host>.container` 和 `projects.<project>.container` 是可选覆盖，与顶层共用全可选模型。已设置的 key
  整体替换下层值（浅层 key 级替换，非深合并），未设置继承下层，优先级 `project > host > global`。覆盖块
  `environment` 同样禁用保留键。
- 拒绝未知字段。Project/instance ID 匹配 `^[a-z0-9][a-z0-9-]{0,31}$`，host alias 匹配
  `^[a-z0-9][a-z0-9.-]{0,62}$`。`hosts` 至少一个；project 的 `host` 列表至少一项、name 不重复且只能引用已配置
  host。project 未配 `image` 时用 `default_image`。

## Host 契约

SSH host ID 必须是本地 `~/.ssh/config` 中可访问 rootful Podman 的现有 alias。workspace 目录以普通 SSH
登录用户身份 `mkdir -p` 创建，无需免密 `sudo`；容器启动时由镜像内 `workspace-init` s6 oneshot 把挂载的
`/workspace` 归属到 `5230:5230`（rootful Podman 直接透传 host 所有权）。身份文件、跳板机、host key policy
由 system OpenSSH 管理。Podman Machine host ID 是逻辑名，对应 machine 必须已存在、运行中且 rootful。

每个 host 必须提供：

- rootful Podman socket（SSH host 默认 `/run/podman/podman.sock`，Podman Machine 通过 `podman machine
  inspect` 获取 API socket 和 SSH identity）；
- SSH 登录用户的可写 home；workspace root 是绝对路径化后的 `~/codespace`；
- GNU `env`（支持 `-0`）读取 `hosts.<host>.environment` 声明且已在非交互 SSH 会话导出的变量；
- `find`（支持 `-mindepth`、`-maxdepth`、`-print0`）供维护工具列出 workspace；
- 允许镜像内 root 将挂载的 `/workspace` `chown` 为 `5230:5230`；
- 为 environment SSH 保留的端口范围 `20000-29999`；
- 一个 host 级 sidecar（见 [`images/sidecar/AGENTS.md`](../images/sidecar/AGENTS.md)，须独立于 project/instance）；
- 满足 [`images/dev/AGENTS.md`](../images/dev/AGENTS.md) 契约的开发镜像。

非原生平台依赖 host 已注册持久化 `binfmt_misc` interpreter（通常 QEMU user-static）。Codespace 只选平台，
不安装或管理模拟器。

## 资源标识

Environment 的 container name、本地 SSH alias 和 deploy-key title 共用确定性 ID `codespace-<host>-<project>-<instance>`。
Host workspace 为 `<login-home>/codespace/<project>/<instance>`，挂载到容器 `/workspace`。SSH 端口为
`20000 + int(sha256(environment_id)[:4], 16) % 10000`；与同 host 其他受管 environment 冲突时直接拒绝，
不探测替代端口。

Podman inventory 是唯一事实来源。Environment container 必须有 `codespace.managed=true` 及完整的 project、
instance、type、image、platform、SSH port label。`codespace.type` 只能 `repo`、`blank` 或 `git`：`repo` 额外
携带 `codespace.repo` 和 `codespace.provider`，`git` 额外携带 `codespace.git-url`，`blank` 三者都不得携带。
未选平台时 platform label 为 `native`。缺失、格式错误、与配置 `type` 不符或引用未知 project 的 label 都是
inventory error，不得推断默认值。sidecar 是 host 级单例，不得复用 environment 的 ID、workspace、deploy key
或 SSH 投影。

## 连接机制

每个 host 维护一个可复用 Podman client。SSH host 另维护一个 system SSH 进程：

```text
ssh -N -o ExitOnForwardFailure=yes -o StreamLocalBindUnlink=yes \
  -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  -L <local.sock>:<host podman_socket> <host>
```

转发目标是解析后的 `podman_socket`，本地 socket 在权限 `0700` 的进程私有 runtime 目录。SSH keepalive 必须
让失效 tunnel 自动退出，Podman 调用必须有超时；进程退出后重建 tunnel，应用关闭时释放 Podman client 和 SSH
子进程。Podman client 与常规 container exec 读超时 60 秒；image pull 用同一 socket 上的临时 Podman client、
15 分钟流数据间隔超时，repository clone 的 exec start 也单独用 15 分钟读超时，不得因此放宽 Dashboard
inventory 等普通 API 的故障边界；临时 pull client 必须在成功或失败后关闭。

Podman Machine 连接从 `podman machine inspect` 读 API socket、SSH 端口和 identity，拒绝已停止或 rootless
machine。Dashboard 并发查询各 host，一个离线 host 不得阻塞其他 host。

## 环境生命周期

控制面启动时先校验 `controller/assets/ssh/` 的 `config`、`known_hosts`、`login_key`，再以 `0600` 原子安装到
`~/.ssh/codespace/`，任一缺失即 fail-fast。该初始化不属于单个 environment 创建流程。

创建顺序不可调整：

1. 校验 inventory、token、重复 ID 和 SSH 端口冲突。
2. 若 `hosts.<host>.environment` 非空，通过非交互 SSH 登录环境读取所有声明变量，任一未导出即失败；只保存本次
   创建所需的内存快照。
3. 内存中生成 environment deploy key。
4. 按所选 host 条目平台拉取镜像；未配置用 host 原生平台。
5. 以 SSH 登录用户身份 `mkdir -p` 创建 host workspace 目录（无需 `sudo`）。
6. 按解析后 `container` 配置创建带完整 label 的 container：非身份 run flag 由 global/host/project 分层解析后
   原样透传、控制面不补默认；第 2 步的 host 环境快照同时注入且不得与显式 `container.environment` 重名。GPU 用
   `container.devices` 的 CDI 名表达。`container.secrets` 在此逐个校验对应 Podman secret 已注册，缺失即
   fail-fast 不创建 container；`mode: mount` 转发 `--secret`（默认 `5230:5230`、`0o400`），`mode: env` 注入
   环境变量、与继承和显式变量共享命名空间且不得重名。解析后 `network_mode` 原样转发 `--network`；`bridge` 下
   注入 `SSHD_BIND=0.0.0.0`、发布 SSH 端口到 loopback、发布 `published_ports` 业务端口。
7. 镜像内 `workspace-init` 先把 `/workspace` `chown` 为 `5230:5230`，之后才允许 `sshd`/`home-init` 启动。
8. `repo` 类型把内存中私钥整体写入镜像预创建的 `/home/x/.ssh/repo_id_ed25519` 并归属 `5230:5230`。Provider
   SSH config 和 pinned `known_hosts` 已由镜像安装，控制面不得生成或覆盖；登录公钥已烤进镜像
   `authorized_keys`，控制面只用仓库内固定登录私钥登录。`blank` 类型不注入任何凭据。
9. 通过生成的 route 完成真实 SSH 登录验证。
10. 将 provider 上同名 deploy key 替换为一个可写 key。
11. 保留 `HEAD` 有效的现有 Git checkout，及带 `.git/codespace-empty-repository` 标记的已成功空仓库 checkout；
    存在 `.git` 但两项均不满足时视为中断 clone 残留并清理，目标路径存在但非 Git checkout 时拒绝覆盖。checkout
    目录取自 `clone_path`（未设时按类型派生），若其父目录不存在先以容器用户 `mkdir -p` 补齐。新 clone
    先清 `<target>.codespace-clone` 临时目录，再以 15 分钟 exec 读超时执行 `git clone --depth=1`，成功后原子
    移动到目标路径；成功 clone 的空仓库写入上述标记。
12. 原子更新 host SSH 投影。

注册 deploy key 前失败时回滚 container 但保留 workspace；注册后失败时必须先撤销 key，撤销失败则停止并保留带
label 的 container，待 token 恢复后重试正常删除。

`blank` 类型跳过仓库相关步骤：不生成或注册 deploy key（步骤 3、10）、不 clone（步骤 11），创建与删除均不需
provider token，其余与 `repo` 一致；因无 checkout 目录，`blank` 在容器内以容器用户身份 `mkdir -p` 其
`open_path`（默认 `/workspace`），保证编辑器打开的是已存在目录。

`git` 类型同样跳过 deploy key 生成/注册（步骤 3、10）与 provider token，但保留步骤 11 的 clone：直接以 15 分钟
exec 读超时 `git clone --depth=1 <git_url>`，凭据与 host key 校验完全依赖镜像内 SSH 契约，checkout 目录取自
`clone_path`，未设时从 URL 末段派生。删除与 `repo` 同样两阶段检测未 push/未提交（见下），但无 provider 状态、不撤销任何 key。

删除 `repo` 类型需 provider token，并在任何远端变更前撤销所有匹配 deploy key（key 不存在视为幂等成功）。
`blank` 与 `git` 无 provider 状态，直接进入 container 与 workspace 处理。`purge=false` 只删 container；
`purge=true` 先停 container、再依 image label 清理 workspace、最后删 container。Provider 失败时不得改变
container 和 workspace。

删除 `repo`/`git` 分两阶段：`force=false` 只在容器内 checkout 目录检测未 push 提交（`git log --branches --not
--remotes`）和未提交/未跟踪改动（`git status --porcelain`），不做任何 container/workspace/provider 变更，
返回 `{deleted, workspace_removed, state}`（`state` 含 `unpushed`、`uncommitted`、`detail`）。WebUI 先以
`force=false` 打开 block 弹窗展示检测，确认后再以 `force=true` 真正删除（`repo` 撤销 deploy key、按 purge 清理
workspace、删 container）。Git 检测仅允许在 `running` container 内执行，不得为预检启动已退出/停止的 container；
WebUI 据 Dashboard status 直接显示未检测警告并允许确认，直接调 `force=false` API 时立即返回错误。`blank` 无
checkout，`state` 恒为空。检测只发生在删除路径，dashboard 不受影响。

## 维护 CLI

四个带外 CLI 都固定读 `~/.config/codespace/config.yaml`，默认 dry-run，仅 `--no-dry-run` 执行写操作，host
查询失败输出 warning 且不影响其他并发查询。

- **Deploy key 清理** `controller.tools.cleanup_deploy_keys`：并发列出配置内全部 GitHub/GitLab 仓库的 deploy
  key，读 host inventory 判断是否仍有对应 container。输出 `Repository`/`Deploy key`/`In use` 三列；`In use`
  为 `yes`/`no`/`unknown`（host 不可用）/`unmanaged`（非 `codespace-` key），后两者不删。`--no-dry-run` 删
  `In use=no`。GitHub 无账号级 deploy key 枚举 API，故已从配置移除的仓库无法自动发现，需先保留或临时恢复对应
  project 配置再清理。
- **Workspace 清理** `controller.tools.cleanup_workspaces`：并发读各 host inventory，列出
  `<login-home>/codespace/<project>/<instance>` 两层目录。输出 `Host`/`Workspace`/`In use` 三列；有对应受管
  container 为 `yes`，符合 ID 规则但无 container 为 `no`，其他为 `unmanaged`（不删）。`--no-dry-run` 删
  `In use=no`：按 host 并发、同 host 内串行，用 `default_image` 启动 root helper container 并只 bind mount
  workspace root，删除目标必须是 workspace root 的严格子路径。
- **Secret 同步** `controller.tools.sync_secrets`：读顶层 `secrets` 明文，把**每个** secret 注册到 `hosts`
  里**每个** host，不做引用分析。输出 `Host`/`Secret`/`Action` 三列；`Action` 为 `create` 或 `replace`
  （已存在，删后重建让 config 值生效）。`--no-dry-run` 才 `podman secret rm` + `create`。顶层 `secrets` 为空
  时空转、不建连接。控制面创建实例时只校验引用的 secret 已存在，从不创建。
- **Sidecar 部署** `controller.tools.deploy_sidecar`：把固定 `codespace-sidecar` 单例部署到**每个 SSH host**
  （`type: ssh`），podman-machine 的 `local` host 用 `run-macos.sh` bridge 启动器、此工具跳过。并发探测各
  host 的 `atuin_db_uri` secret 与已有容器：输出 `Host`/`Sidecar`/`Action` 三列，`Action` 为 `create` 或
  `replace`（已存在，先删后重建）；secret 缺失的 host 输出 warning 并跳过（先用 `sync_secrets` 注册）。
  `--no-dry-run` 才 `podman pull` 固定镜像、按名替换旧容器，并以 host network、`unless-stopped` restart
  policy、bind-mount 宿主 rootful Podman socket 到 `/run/podman/podman.sock`、`atuin_db_uri` 以 `env` 注入
  `ATUIN_DB_URI` 的方式启动，等价 `images/sidecar/run-linux.sh`。无 SSH host 时空转、不建连接。

## SSH 投影

`~/.ssh/config` 只增加 `Include ~/.ssh/codespace/config`。Codespace 完全管理
`~/.ssh/codespace/config`、`login_key`、`known_hosts/` 和 `hosts/*.conf`：固定文件从
`controller/assets/ssh/` 原子安装；只有 inventory 成功后才重写 host 投影，host 离线时保留最后版本，从 YAML
移除后才删除。

静态 `config` 通过 `Host codespace-*` 统一声明 `HostName 127.0.0.1`、用户 `x`、managed `IdentityFile` 和
host-key policy；动态 `hosts/*.conf` 每个 environment 只声明确定性端口和 `ProxyJump`/`ProxyCommand`。登录
公钥已烤进镜像 `authorized_keys`，控制面不再生成或注入。所有 environment 共用镜像内固定 sshd ed25519 host
key，通过 `HostKeyAlias codespace` 指向单个 pinned `~/.ssh/codespace/known_hosts/codespace`，并用
`StrictHostKeyChecking yes` 校验；该 asset 必须与 `images/dev/rootfs/etc/ssh/ssh_host_ed25519_key.pub` 一致，
改镜像 host key 必须同步更新它。SSH host 用 `ProxyJump <host>`；Podman Machine 用 inspect 结果构造的专用
`ProxyCommand`，其 `machine-<host>` known-hosts 校验 VM 自身 host key（与镜像无关），保持 accept-new。不得
解析或合并历史 SSH block。

## Web 契约

应用固定单 worker、监听 `127.0.0.1:8003`（前台 `uv run python -m controller`，后台 `controller/run.sh`）。
只保留以下 API：

- `GET /api/dashboard`
- `PUT /api/tokens/{provider}`
- `POST /api/projects/{project}/instances`（body 含 `host` 和 `instance`）
- `GET /api/projects/{project}/hosts/{host}/instances/{instance}/logs`
- `DELETE /api/projects/{project}/hosts/{host}/operations/{instance}`
- `DELETE /api/projects/{project}/hosts/{host}/instances/{instance}?purge=true|false&force=true|false`

错误格式固定 `{"error": "..."}`。创建 body 用 `host` 显式选 project 声明的某个 host，不在列表内即拒绝。
`GET .../logs` 只读，返回 `{"logs": "..."}`（container 最近合并 stdout/stderr、带时间戳、末尾 2000 行），不
存在的 environment 返回 `{"error": ...}`；Web UI 用只读 Logs 弹窗展示，支持手动 Refresh，不轮询、不流式。
`DELETE` 路径带 `host`（同名 instance 可分布在不同 host，identity 由 host+project+instance 决定），成功返回
`{deleted, workspace_removed, state}`，`force=false` 时 `deleted=false` 且 `state` 携带 git 检测结果。
Dashboard response 是浏览器唯一事实来源；每个 project summary 携带 `hosts` 列表（各含 `name` 和可选
`platform`），Web UI 为每个 environment 显示完整 `ssh_command`，点击经 Clipboard API 复制并显示短暂反馈。
创建对话框先选 host（Quick Create 用列表首个 host），只在 create operation 为 queued/running 时轮询。失败的
create operation 保留错误信息并提供关闭按钮调 operation `DELETE` 清理；该 API 只允许清理 `failed`，对不存在的
operation 幂等返回 `{"dismissed": false}`，不得隐藏 queued/running operation。不得增加 SSE、前端 optimistic
state、OpenAPI 页面或独立 host/port 配置。

## 安全边界

- Rootful Podman socket 等同 host root 权限；必须保留 system OpenSSH host-key verification。
- Provider token 只能发给选定 Git provider，不得返回或写日志。配置文件中的 token 是明文，只能本地保存、限制
  权限并排除版本控制，控制面不得回写。
- `controller/__init__.py` 导入时调用 `truststore.inject_into_ssl()`，让 HTTPS provider 复用操作系统信任库
  （macOS Keychain / Linux 系统 CA）以信任公司 TLS 网关重签发证书；不得改回仅信任 certifi，也不得关闭 TLS 校验。
- Deploy private key 只能存在于对应开发容器。
- 应用级密钥由 host operator 用 `podman secret create` 预注册，控制面只按名字引用、绝不持有明文、不回写落盘。
  secret 明文只在容器内出现：`mode: mount` 默认 `0o400`、归属 `5230:5230`，`mode: env` 只存于容器进程环境；
  日志不得出现 secret 明文。顶层 `secrets` 块是唯一例外明文来源，仅供带外 `sync_secrets` 使用，启用后
  `config.yaml` 含明文密钥、须限制权限并排除版本控制，控制面运行时仍不读取。
- 开发容器访问 GitHub/GitLab 必须用镜像内 pinned `known_hosts` 做严格 host key 校验。
- 登录 keypair 是固定、提交进仓库的共享凭据，公钥烤进镜像。该方案仅面向内网、配置不存 IP/port，威胁模型下
  私钥泄露无实质影响；不得用它保护任何对外可达的 host。
- Web 应用不得远程暴露，也不得增加 worker。
- Sidecar 共享服务只经 host loopback 暴露；bridge container 只有在 host publish 限为 `127.0.0.1` 时内部才可
  绑所有接口。

## 变更规则

- 修改 Codespace 配置、生命周期、API、host contract：同步更新本文相关章节；涉及 sidecar 更新
  [`images/sidecar/AGENTS.md`](../images/sidecar/AGENTS.md)，涉及开发镜像更新 [`images/dev/AGENTS.md`](../images/dev/AGENTS.md)。
- 本地控制面的 Python、静态资源、启动器和测试全保留在 `controller/`。
- 优先添加针对受影响模块的聚焦测试；不恢复已删除的兼容目录、远端 Python agent 或 Node Web 构建链。
