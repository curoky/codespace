# Codespace 设计约束

本文是 `codespace/` 的架构、生命周期、API 和 host contract 的事实来源。相关行为变化时
必须同步更新本文。

## 范围

Codespace 是仅监听 localhost 的单进程开发容器控制面，支持远端 rootful Podman host 和
本地 rootful Podman Machine。Python 进程通过 system OpenSSH 转发远端 Podman Unix
socket；Podman Machine 使用 `podman machine inspect` 返回的本地 API socket。

不得增加远端 HTTP agent，也不得改用 podman-py 的 SSH adapter。

FastAPI 同时提供 JSON API 和 `client/static/` 中的原生 Web 文件。GitHub、GitLab token
只保存在进程内存中；`config.yaml` 的可选 `tokens` 可提供启动值，Web UI 可在运行时覆盖。

## 目录

| 路径 | 职责 |
| --- | --- |
| `client/app.py`、`client/__main__.py` | Web 应用与入口 |
| `client/config.py`、`client/models.py` | 配置与 API model |
| `client/transport.py`、`client/runtime.py` | SSH 与 Podman 基础能力 |
| `client/service.py`、`client/operations.py` | 编排与操作状态 |
| `client/provider.py`、`client/ssh.py` | Deploy key 与 SSH 投影 |
| `client/static/` | FastAPI 直接提供的原生 Web 源码 |
| `client/tests/` | 按公开模块行为组织的测试 |
| `client/run.sh` | 本地后台启动器 |
| `images/dev/` | 参考开发镜像 |
| `images/sidecar/` | Host 级共享服务镜像 |

本地控制面代码全部放在 `client/`。不得恢复 `agent/`、顶层兼容模块、生成式 Web 产物或
Node.js 构建链。

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

hosts:
  local:
    type: podman-machine
    machine: podman-machine-default
    container:
      network_mode: bridge
  office:
    podman_socket: /tmp/podmanxd.sock
  gpu-box:
    container:
      pids_limit: 4096
      devices:
        - nvidia.com/gpu=all
  home:

projects:
  devspace:
    host: home
    repo: github:curoky/devspace
    description: Devspace repository
  service-api:
    host: office
    repo: gitlab:group/service-api
    image: registry.example.com/codespace-api:latest
    platform: linux/arm64
    container:
      environment:
        NODE_ENV: development
  scratch:
    host: home
    type: blank
    open_path: /workspace/notes

tokens:
  github: ghp_xxx
  gitlab: glpat-xxx
```

顶层必填字段是 `default_image`、`hosts` 和 `projects`；`container` 可选（省略即全部使用引擎
默认）。登录容器所用的固定 keypair 私钥（`codespace/client/assets/codespace_login_key`）由
控制面按模块相对路径定位，无需配置；对应公钥已烤进开发镜像的 `authorized_keys`。`hosts` 是以 host alias
为 key 的映射，值为该 host 的连接设置；host 值可以留空（等价默认 SSH host）。每个 project
必须包含 `host`，并按 `type` 决定 repo 相关字段，可选 `description`、`image`、`platform`、
`open_path`、`published_ports` 和 `container`。其他规则如下：

- `type` 默认 `repo`，也可设为 `blank`。`repo` 类型必须配置 `repo`（因此带 `provider`）；
  `blank` 类型禁止配置 `repo` 和 `provider`。
- `repo` 写成 `<provider>:<owner>/<name>`，`provider` 只能是 `github` 或 `gitlab`。
- `open_path` 可选，必须是绝对路径；未设置时 `repo` 类型默认打开仓库目录，`blank` 类型默认
  打开挂载点 `/workspace`。编辑器 deep link 按此路径打开。
- `platform` 只能是 `linux/amd64` 或 `linux/arm64`；省略时使用 host 原生平台。
- `published_ports` 可选，是要发布到宿主机的端口列表，每项写成 `"<remote>"`（local=remote）
  或 `"<local>:<remote>"`，端口取值 1-65535，同一 project 内 local 端口不得重复。只有解析后
  `container.network_mode` 为 `bridge` 的 project 可配置 `published_ports`（bridge 容器有独立
  netns 才能发布端口），解析为 `host` 时配置 `published_ports` 直接拒绝。改动
  `published_ports` 需重建实例才生效。
- `hosts.<host>.type` 默认是 `ssh`，也可设为 `podman-machine`。
- SSH host 可配置绝对路径 `podman_socket`，默认 `/run/podman/podman.sock`，不得配置
  `machine`。
- Podman Machine host 必须配置 `machine`，不得配置 `podman_socket`。
- `tokens` 中的 `github`、`gitlab` 是可选的非空字符串。
- 顶层 `container` 是可选块，承载所有非身份的容器 run flag，采用 Docker Compose service 的
  字段名与语法子集（解析实现独立在 `client/compose/` 子包中，只做强类型化，不含控制面知识），
  控制面自身不保留任何隐式默认值。所有字段（`network_mode`、`cap_add`、`security_opt`、
  `pids_limit`、`ulimits`、`volumes`、`environment`、`devices`，对应 `--network`、`--cap-add`、
  `--security-opt`、`--pids-limit`、`--ulimit`、`--device`）全部可选，未设置等价于 Compose 语义
  下的「引擎默认」：在 runtime 边界处集合归一为空、`pids_limit` 仅在设置时才转发给 `podman run`。
  `network_mode` 只能是 `host` 或 `bridge`，原样转发给 `--network`：`host` 让容器共享 host netns；
  `bridge` 让容器获得独立 netns，sshd 注入 `SSHD_BIND=0.0.0.0` 并发布 SSH 端口和业务端口。虽然
  compose 语义下 `network_mode` 可省略，但控制面要求**每个 project 分层解析后必须有确定的
  `network_mode`**（缺失即在加载时 fail-fast），因此实践中通常在顶层 `container` 设一次全局默认。
  `ulimits` 是以限制名为 key 的映射，值为 `{soft, hard}` 或裸整数（等价 soft=hard）。`volumes`
  支持 Compose 短语法 `source:target[:ro|rw]` 或长语法
  `{type: bind, source, target, read_only}`；只支持 `type: bind`，`source`/`target` 必须是绝对
  路径，`read_only` 默认 `false`。`devices` 是原样转发给 `--device` 的字符串列表，GPU 访问用 CDI
  设备名表达（如 `nvidia.com/gpu=all`），要求该 host 已安装 NVIDIA 驱动与 CDI 规范文件。
  `environment` 是透传给容器的环境变量，支持映射或
  `["KEY=value"]` 列表短语法，禁止使用控制面派生的保留键 `SSHD_PORT`、`SSHD_BIND`。这些值原样
  转发给 `podman run`，控制面不做任何转换。
- `hosts.<host>.container` 和 `projects.<project>.container` 是可选覆盖，与顶层 `container`
  共用同一个全可选模型。已设置的 key 整体替换对应的下层值（浅层 key 级替换，非深合并），未设置
  （`None`）的 key 继承下层值。优先级 `project > host > global`。覆盖块的 `environment` 同样禁止
  保留键。
- 拒绝未知字段。
- Project 和 instance ID 匹配 `^[a-z0-9][a-z0-9-]{0,31}$`。
- Host alias 匹配 `^[a-z0-9][a-z0-9.-]{0,62}$`。
- `hosts` 至少包含一个 host；project 只能引用已配置的 host。
- Project 未配置 `image` 时使用 `default_image`。

## Host 契约

SSH host ID 必须是本地 `~/.ssh/config` 中可访问 rootful Podman 的现有 alias。workspace
目录以普通 SSH 登录用户身份创建（`mkdir -p`），无需免密 `sudo`；容器创建后由容器内 root
执行 `chown` 将挂载的 `/workspace` 归属到 `5230:5230`（rootful Podman 直接透传 host
所有权）。身份文件、跳板机和 host key policy 由 system OpenSSH 管理。

Podman Machine host ID 是 Codespace 内的逻辑名称；对应 machine 必须已存在、正在运行且
使用 rootful 模式。

每个 host 必须提供：

- rootful Podman socket；SSH host 默认是 `/run/podman/podman.sock`，Podman Machine
  通过 `podman machine inspect` 获取 API socket 和 SSH identity；
- SSH 登录用户的可写 home；workspace root 是绝对路径化后的 `~/codespace`；
- 将挂载的 `/workspace` 由容器内 root `chown` 为 `5230:5230` 的权限；
- 为 environment SSH 保留的端口范围 `20000-29999`；
- 一个 host 级 sidecar；
- 满足下述契约的开发镜像。

非原生平台依赖 host 已注册持久化 `binfmt_misc` interpreter，通常为 QEMU user-static。
Codespace 只选择平台，不安装或管理模拟器。

开发镜像必须提供：

- 用户 `x`，uid/gid 为 `5230:5230`；
- 可写的 `/workspace`；
- 默认 host network，sshd 监听地址由 `SSHD_BIND` 环境变量控制，默认 `127.0.0.1`；
- Podman security option `disable` 和 `seccomp=unconfined`；
- 现有 s6 entrypoint、sshd、onceinit、Atuin client、Git 和 OpenSSH client。

`network_mode: host` 的容器使用 host network，sshd 绑定 `127.0.0.1`。`network_mode: bridge`
的容器改用 bridge network：sshd 注入 `SSHD_BIND=0.0.0.0`，SSH 端口发布到 loopback
`127.0.0.1:<ssh_port>` 以复用现有 ProxyCommand 路径，project `published_ports` 声明的业务
端口发布后经 gvproxy 转发到 macOS `localhost:<local>`。

Sidecar 镜像和网络细节见
[`images/sidecar/CLAUDE.md`](images/sidecar/CLAUDE.md)。它必须独立于 project 和
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
tunnel，应用关闭时释放 Podman client 和 SSH 子进程。

Podman Machine 连接从 `podman machine inspect` 读取 API socket、SSH 端口和 identity；
拒绝已停止或 rootless machine。Dashboard 并发查询各 host，一个离线 host 不得阻塞其他
host。

## 环境生命周期

创建顺序不可调整：

1. 校验 inventory、token、重复 ID 和 SSH 端口冲突。
2. 校验仓库内固定登录私钥存在并收紧其权限为 `0600`（缺失即 fail-fast）。
3. 在内存中生成 environment deploy key。
4. 按 project 平台拉取镜像；未配置时使用 host 原生平台。
5. 以 SSH 登录用户身份创建 host workspace 目录（`mkdir -p`，无需 `sudo`）。
6. 按解析后的 `container` 配置创建带完整 label 的 container：非身份 run flag（`network_mode`、
   `cap_add`、`security_opt`、`pids_limit`、`ulimits`、`devices`、额外 `volumes` 和
   `environment`）由 global/host/project 分层解析后原样透传，控制面不补默认。GPU 通过
   `container.devices` 里的 CDI 设备名（如 `nvidia.com/gpu=all`）表达。解析后的
   `container.network_mode` 原样转发给 `--network`；`bridge` 模式下
   注入 `SSHD_BIND=0.0.0.0`，发布 SSH 端口到 loopback，并发布 project `published_ports`
   声明的业务端口。
7. 由容器内 root `chown` 将挂载的 `/workspace` 归属到 `5230:5230`。
8. 整体写入 Codespace 管理的仓库 SSH 凭据。登录公钥不再注入：它已烤进开发镜像的
   `authorized_keys`，控制面只用仓库内固定的登录私钥登录。容器是 Codespace 独占的新建
   资源，`repo_id_ed25519` 和 provider `~/.ssh/config` 均整文件覆盖，不读取或合并容器内既有
   内容。`blank` 类型不注入任何凭据。
9. 通过生成的 route 完成真实 SSH 登录验证。
10. 将 provider 上同名 deploy key 替换为一个可写 key。
11. 保留现有 Git checkout，或 clone 配置的 repository。
12. 原子更新 host SSH 投影。

注册 deploy key 前失败时，回滚 container 但保留 workspace。注册后失败时，必须先撤销
key；撤销失败则停止并保留带 label 的 container，待 token 恢复后重试正常删除。

`blank` 类型 project 跳过与仓库相关的步骤：不生成或注册 deploy key（步骤 3、10），不 clone
repository（步骤 11），创建与删除均不需要 provider token；其余步骤与 `repo` 类型一致。由于没有
clone 产生的 checkout 目录，`blank` 类型在容器内以容器用户身份 `mkdir -p` 其 `open_path`
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
清理 workspace、删除 container）。`blank` 类型无 checkout，`state` 恒为空。检测只发生在删除
路径，dashboard 不受影响。

## SSH 投影

`~/.ssh/config` 中只增加一个 include：

```sshconfig
Include ~/.ssh/codespace/config
```

Codespace 完全管理 `~/.ssh/codespace/config` 和 `hosts/*.conf`。只有 inventory 成功后
才能重写 host 投影；host 离线时保留最后版本，从 YAML 移除后才删除。

每个 environment 使用 `HostName 127.0.0.1`、确定性端口、用户 `x` 和全局登录 key。登录 key 是
仓库内提交的固定 keypair 私钥（`client/ssh.py` 的 `LOGIN_KEY_PATH` 按模块相对路径定位），其
`IdentityFile` 在 host 投影里直指该绝对路径；对应公钥已烤进开发镜像的 `authorized_keys`，控制面
不再生成或注入登录公钥，也不需要配置项。所有
environment 运行同一开发镜像、共用镜像内固定的 sshd ed25519 host key，因此不再为每个
environment 维护独立 known-hosts 文件：全部 environment 通过固定 `HostKeyAlias codespace`
指向单个被 pin 的 `~/.ssh/codespace/known_hosts/codespace`，并用 `StrictHostKeyChecking yes`
做真实校验（key 不符即拒绝，而非 accept-new 的首次盲信）。被 pin 的 host key 作为
code-level 契约常量固化在 `client/ssh.py`（`IMAGE_HOST_KEY`），与镜像
`images/dev/rootfs/etc/ssh/ssh_host_ed25519_key.pub` 一致；改镜像 host key 必须同步更新它。
SSH host 使用 `ProxyJump <host>`；Podman Machine 使用由 inspect 结果构造的专用
`ProxyCommand`，其 `machine-<host>` known-hosts 校验的是 VM 自身 host key（与镜像 host key
无关），保持 accept-new。不得解析或合并历史 SSH block。

## Web 契约

前台启动：

```bash
uv run python -m codespace.client
```

后台启动并将日志保存在仓库内：

```bash
codespace/client/run.sh
```

应用固定使用单 worker 并监听 `127.0.0.1:8003`。只保留以下 API：

- `GET /api/dashboard`
- `PUT /api/tokens/{provider}`
- `POST /api/projects/{project}/instances`
- `DELETE /api/projects/{project}/instances/{instance}?purge=true|false&force=true|false`

错误格式固定为 `{"error": "..."}`。`DELETE` 成功返回 `{deleted, workspace_removed, state}`，
`force=false` 时 `deleted=false` 且 `state` 携带 git 检测结果。Dashboard response 是浏览器的唯一事实来源。只在
create operation 处于 queued 或 running 时轮询。不得增加 SSE、operation dismissal、
前端 optimistic state、OpenAPI 页面或独立 host/port 配置。

## 安全边界

- Rootful Podman socket 等同于 host root 权限。
- 必须保留 system OpenSSH host-key verification。
- Provider token 只能发送给选定 Git provider，不得返回或写入日志。配置文件中的 token
  是明文，只能本地保存、限制权限并排除版本控制；控制面不得回写。
- Deploy private key 只能存在于对应开发容器。
- 登录 keypair 是固定的、提交进仓库的共享凭据，公钥烤进开发镜像。该方案仅面向内网、且配置不
  存放 IP/port，威胁模型下私钥泄露无实质影响；不得用它保护任何对外可达的 host。
- Web 应用不得远程暴露，也不得增加 worker。
- Sidecar 共享服务只能通过 host loopback 暴露；bridge container 只有在 host publish
  限制为 `127.0.0.1` 时，内部才可绑定所有接口。

## 变更规则

- 不修改 `images/dev/` 中与任务无关的 s6、Atuin client、Ollama、onceinit 和 sshd。
- Host 共享服务资产只能放在 `images/sidecar/`，不能进入 project 生命周期模块。
- Sidecar inventory 与 environment inventory 必须分离。
- Sidecar 不得恢复 Python HTTP agent、Podman socket 或 workspace mount。
- 本地控制面的 Python、静态资源、启动器和测试全部保留在 `client/`。
- Sidecar 的命名、label、image、storage 或生命周期确定后，同时更新本文和
  `images/sidecar/CLAUDE.md`。
- 优先添加针对受影响模块的聚焦测试，不恢复兼容路径。

## 验证

先运行最小相关检查，再运行完整 Codespace 检查：

```bash
uv run ruff format --check codespace/client
uv run ruff check codespace/client
uv run mypy codespace/client
uv run pytest codespace/client/tests
uv lock --check
```
