# Codespace 设计约束

本文是 `codespace/` 的架构、生命周期、API 和 host contract 的事实来源。相关行为变化时
必须同步更新本文。

## 范围

Codespace 是仅监听 localhost 的单进程开发容器控制面，支持远端 rootful Podman host 和
本地 rootful Podman Machine。Python 进程通过 system OpenSSH 转发远端 Podman Unix
socket；Podman Machine 使用 `podman machine inspect` 返回的本地 API socket。

不得增加远端 HTTP agent，也不得改用 podman-py 的 SSH adapter。

FastAPI 同时提供 JSON API 和 `client/static/` 中的原生 Web 文件。GitHub、GitLab token
只保存在进程内存中；`config.toml` 的可选 `[tokens]` 可提供启动值，Web UI 可在运行时覆盖。

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

进程启动时只读取 `~/.config/codespace/config.toml`。不得增加 YAML、环境变量覆盖、热加载
或备用配置源。

```toml
default_image = "ghcr.io/curoky/devspace:codespace-debian13"
hosts = ["local", "home", "office"]

[projects.devspace]
host = "home"
provider = "github"
repo = "curoky/devspace"
description = "Devspace repository"

[projects.service-api]
host = "office"
provider = "gitlab"
repo = "group/service-api"
image = "registry.example.com/codespace-api:latest"
platform = "linux/arm64"

[host_options.office]
podman_socket = "/tmp/podmanxd.sock"

[host_options.local]
type = "podman-machine"
machine = "podman-machine-default"

[tokens]
github = "ghp_xxx"
gitlab = "glpat-xxx"
```

顶层必填字段是 `default_image` 和 `hosts`。每个 project 必须包含 `host`、`provider`、
`repo`，可选 `description`、`image` 和 `platform`。其他规则如下：

- `platform` 只能是 `linux/amd64` 或 `linux/arm64`；省略时使用 host 原生平台。
- `host_options.<host>.type` 默认是 `ssh`，也可设为 `podman-machine`。
- SSH host 可配置绝对路径 `podman_socket`，默认 `/run/podman/podman.sock`，不得配置
  `machine`。
- Podman Machine host 必须配置 `machine`，不得配置 `podman_socket`。
- `[tokens]` 中的 `github`、`gitlab` 是可选的非空字符串。
- 拒绝未知字段。
- Project 和 instance ID 匹配 `^[a-z0-9][a-z0-9-]{0,31}$`。
- Host alias 匹配 `^[a-z0-9][a-z0-9.-]{0,62}$`。
- `hosts` 不得重复；project 和 `host_options` 只能引用已配置的 host。
- Project 未配置 `image` 时使用 `default_image`。

## Host 契约

SSH host ID 必须是本地 `~/.ssh/config` 中可访问 rootful Podman 的现有 alias。非 root
登录必须支持免密 `sudo -n`，以便为 workspace 设置容器用户所有权。身份文件、跳板机和
host key policy 由 system OpenSSH 管理。

Podman Machine host ID 是 Codespace 内的逻辑名称；对应 machine 必须已存在、正在运行且
使用 rootful 模式。

每个 host 必须提供：

- rootful Podman socket；SSH host 默认是 `/run/podman/podman.sock`，Podman Machine
  通过 `podman machine inspect` 获取 API socket 和 SSH identity；
- SSH 登录用户的可写 home；workspace root 是绝对路径化后的 `~/codespace2`；
- 将每个 environment workspace 设为 `5230:5230` 的权限；
- 为 environment SSH 保留的端口范围 `20000-29999`；
- 一个 host 级 sidecar；
- 满足下述契约的开发镜像。

非原生平台依赖 host 已注册持久化 `binfmt_misc` interpreter，通常为 QEMU user-static。
Codespace 只选择平台，不安装或管理模拟器。

开发镜像必须提供：

- 用户 `x`，uid/gid 为 `5230:5230`；
- 可写的 `/workspace`；
- host network，且 sshd 只绑定 `127.0.0.1`；
- Podman security option `disable` 和 `seccomp=unconfined`；
- 现有 s6 entrypoint、sshd、onceinit、Atuin client、Git 和 OpenSSH client。

Sidecar 镜像和网络细节见
[`images/sidecar/CLAUDE.md`](images/sidecar/CLAUDE.md)。它必须独立于 project 和
instance 资源。

## 资源标识

Environment 的 container name、本地 SSH alias 和 deploy-key title 共用确定性 ID：

```text
codespace-<host>-<project>-<instance>
```

Host workspace 为 `<login-home>/codespace2/<project>/<instance>`，挂载到容器
`/workspace`。SSH 端口计算公式是：

```text
20000 + int(sha256(environment_id)[:4], 16) % 10000
```

若与同一 host 上其他受管 environment 冲突，直接拒绝，不探测替代端口。

Podman inventory 是唯一事实来源。Environment container 必须具有
`codespace.managed=true`，以及完整的 project、instance、repo、provider、image、
platform、SSH port label。未选择平台时 platform label 是 `native`。缺失、格式错误或
引用未知 project 的 label 都是 inventory error，不得推断默认值。

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
2. 生成或复用 `~/.ssh/codespace/id_ed25519`。
3. 在内存中生成 environment deploy key。
4. 按 project 平台拉取镜像；未配置时使用 host 原生平台。
5. 创建 host workspace 并设为 `5230:5230`；非 root SSH 登录使用 `sudo -n`。
6. 用固定参数创建带完整 label 的 host-network container。
7. 写入 Codespace 管理的登录与仓库 SSH 凭据，合并受管 `~/.ssh/config` block。
8. 通过生成的 route 完成真实 SSH 登录验证。
9. 将 provider 上同名 deploy key 替换为一个可写 key。
10. 保留现有 Git checkout，或 clone 配置的 repository。
11. 原子更新 host SSH 投影。

注册 deploy key 前失败时，回滚 container 但保留 workspace。注册后失败时，必须先撤销
key；撤销失败则停止并保留带 label 的 container，待 token 恢复后重试正常删除。

删除需要 provider token，并在任何远端变更前撤销所有匹配 deploy key。Key 已不存在视为
幂等成功。`purge=false` 只删除 container；`purge=true` 先停止 container，再依据其 image
label 清理 workspace，最后删除 container。Provider 失败时不得改变 container 和 workspace。

## SSH 投影

`~/.ssh/config` 中只增加一个 include：

```sshconfig
Include ~/.ssh/codespace/config
```

Codespace 完全管理 `~/.ssh/codespace/config` 和 `hosts/*.conf`。只有 inventory 成功后
才能重写 host 投影；host 离线时保留最后版本，从 TOML 移除后才删除。

每个 environment 使用 `HostName 127.0.0.1`、确定性端口、用户 `x`、全局登录 key 和独立
known-hosts 文件。SSH host 使用 `ProxyJump <host>`；Podman Machine 使用由 inspect 结果
构造的专用 `ProxyCommand`。不得解析或合并历史 SSH block。

## Web 契约

前台启动：

```bash
uv run python -m codespace.client
```

后台启动并将日志保存在仓库内：

```bash
codespace/client/run.sh
```

应用固定使用单 worker 并监听 `127.0.0.1:8765`。只保留以下 API：

- `GET /api/dashboard`
- `PUT /api/tokens/{provider}`
- `POST /api/projects/{project}/instances`
- `DELETE /api/projects/{project}/instances/{instance}?purge=true|false`

错误格式固定为 `{"error": "..."}`。Dashboard response 是浏览器的唯一事实来源。只在
create operation 处于 queued 或 running 时轮询。不得增加 SSE、operation dismissal、
前端 optimistic state、OpenAPI 页面或独立 host/port 配置。

## 安全边界

- Rootful Podman socket 等同于 host root 权限。
- 必须保留 system OpenSSH host-key verification。
- Provider token 只能发送给选定 Git provider，不得返回或写入日志。配置文件中的 token
  是明文，只能本地保存、限制权限并排除版本控制；控制面不得回写。
- Deploy private key 只能存在于对应开发容器。
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
