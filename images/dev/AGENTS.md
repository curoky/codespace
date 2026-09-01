# 开发镜像约束

`images/dev/` 构建 Codespace 基础与参考开发镜像，组合 `/opt/bm` 静态工具、Nix、Rust、Java、
Node.js、Go、uv、Conda、dotfiles 和自建 s6 init。

本文是开发镜像结构、s6 init、容器 SSH 契约与镜像 host contract 的事实来源。整体架构见仓库根
[`AGENTS.md`](../../AGENTS.md)，消费方契约见 [`controller/AGENTS.md`](../../controller/AGENTS.md)，
host 级共享服务见 [`images/sidecar/AGENTS.md`](../sidecar/AGENTS.md)，容器内工具路径见
[`dev-environment.md`](dev-environment.md)。修改本目录契约时必须同步更新本文。

## 目录

| 路径 | 职责 |
| --- | --- |
| `Dockerfile` | 组装静态工具、Nix、各语言运行时、dotfiles 和自建 s6 init |
| `build.sh` | 从仓库根构建本地开发镜像 |
| `script/` | 构建脚本，含 remote server 扩展安装与 s6 配置 |
| `rootfs/` | 烤进镜像的 s6、sshd、SSH host key 和跨场景 home 配置 |
| `rootfs/opt/codespace/` | 独立 uv application、workspace agent 与单职责 runtime helper |
| `tests/` | `/opt/codespace/bin/` helper 的 Bats 行为测试 |
| `dev-environment.md` | 容器内工具链路径与使用方式 |

## s6 init

开发镜像不用 s6-overlay。`script/setup-s6.sh` 从 `/opt/bm/store` 的 s6/execline 二进制生成
`/etc/s6/init` 和 `/etc/s6/db`。新增服务放入 `rootfs/etc/s6/s6-rc.d/` 并加入 bundle；execline 脚本用
`s6-envdir -Lf -- /run/s6/container_environment` 读容器环境，该目录仅 root 和 `x` 可读。每个服务的
`up`/`run` 只是「设置 fd/env 后 `exec` 一个 `/opt/codespace/bin/` 编排脚本」的纯壳，逻辑都在 helper 里。

runlevel 只有一层：`user-base` 含全部服务，`user-final` 嵌套它作为 maker 默认 runlevel。服务清单：

- **`workspace-init`**（oneshot，唯一 workspace 就绪门控，以 `x` 起）：`sudo chown` `/workspace`、
  `/workspace.enc`、`/upload`、`/cache` 到 `5230:5230`，再按加密开关挂载 `/workspace`（见 host contract）。
  `sshd` 与两个 WebDAV 依赖它。
- **`home-init`**（oneshot，以 `x` 起，不依赖 `workspace-init`）：`sudo chown` 五个 IDE home mount，
  无条件生成或复用容器内 deploy key，再做扩展播种、docker scene dotfiles、agent playbook 与 user rules。
  `workspace-agent` 依赖它。
- **`gitconfig-init`**（oneshot，以 `x` 起）：幂等写入 Git 全局身份。
- **`workspace-agent`**：按容器环境变量 `CODESPACE_WORKSPACE_TYPE` 是否注入自门控——未注入
  （devcontainer、WSL、裸 `podman run` 等通用镜像场景）时 `signal.pause()` 空转，不 bootstrap、不监听
  `agent.sock`；deploy key 由 `home-init` 无条件生成，不受此门控影响。
- 其余 longrun：`sshd`、`rclone-webdav`、`copyparty-webdav`、`atuin-login`/`atuin-daemon`、`ollama`、
  `supercronic`。

## 容器 SSH 契约

Container 专用 SSH config 位于 `rootfs/home/x/.ssh/config`，为 `Host *` 启用 GSSAPI 认证与凭据委派，
并固定用 `~/.ssh/repo_id_ed25519` 访问 GitHub/GitLab，构建时收紧为 `0600`；不得复用带 host 凭据代理的
`dotfiles/ssh/user.ssh_config`。GitHub/GitLab host key 固定在同目录 `known_hosts`，provider 连接必须
`StrictHostKeyChecking yes`，不得回退到 `accept-new`。该 private key 由 `home-init` 在容器内生成，控制面
只读取对应公钥。

控制面的 `git` 类型 workspace 直接 clone 任意内网 `git@host:owner/name.git`（或 `ssh://` 形式）URL，不注入
deploy key。此类连接的认证与 host key 校验完全由本契约承担：内网 host 通常经 `Host *` 的 GSSAPI/Kerberos
（配合宿主 `/etc/krb5.conf` bind-mount）认证；host key 必须预置在同目录 `known_hosts`，`StrictHostKeyChecking
yes` 下未预置的 host 会被拒绝。新增内网 git host 需在此同步 host key。

## 镜像 host contract

开发镜像必须提供：

- 用户 `x`（uid/gid `5230:5230`）、可写的 `/workspace`、`/upload` 与 `/cache`，均由控制面按实例
  bind-mount `~/codespace/workspaces/<workspace>/<instance>/` 下的同名子目录；`cache/` 下五个 IDE 子目录还
  分别直接 bind-mount 到 `/home/x/.vscode-server`、`/home/x/.trae`、`/home/x/.trae-cn`、`/home/x/.trae-server`
  与 `/home/x/.trae-cn-server`。控制面把 `control/` bind-mount 到 `/run/codespace-control`，该目录保持 login
  user 所有、mode `0700`，不由 `workspace-init` chown。
- 默认 host network，sshd 监听地址由 `SSHD_BIND` 控制（默认 `127.0.0.1`）；Podman security option `disable`
  与 `seccomp=unconfined`；`/run/s6/container_environment` 仅 root 和 `x` 可读。
- **`workspace-init`**（`up` 用 `s6-setuidgid x`，日志 `/var/log/workspace-init.log`）：先 `sudo chown`
  （`x` 有 NOPASSWD sudo，见 `setup-sysconf.sh`）把 `/workspace`、`/workspace.enc`、`/upload`、`/cache` 归属到
  `5230:5230`（数据 mount 由控制面按实例 bind，rootful Podman 透传所有权），五个 IDE home 目录的 chown 归
  `home-init`。加密挂载以 `WORKSPACE_CRYPT_KEY` 是否注入为信号（对齐控制面 `encrypt_workspace`）：未注入则
  `/workspace` 保持明文 bind；注入则用 gocryptfs（`/opt/bm/bin/gocryptfs`）把密文根 `/workspace.enc` 解密挂到
  `/workspace`，缺 `gocryptfs.conf` 时先 `-init`。gocryptfs 依赖 FUSE：容器须有 `/dev/fuse` 与 `SYS_ADMIN`
  （或 security option `disable`），镜像预置 `/etc/fuse.conf` 的 `user_allow_other` 以支持 `-allow_other`。
  gocryptfs 经 PATH 调用 `fusermount3`（binman `link` 装 `fuse3` 提供），且以 `x` 挂载而 `x` 无
  CAP_SYS_ADMIN，故 `setup-sysconf.sh` 构建期给 `fusermount3` 加 setuid root；FUSE 守护进程以 `x` 身份读写
  密文根，落盘密文属主即 `5230:5230`。
- **`gitconfig-init`**：baked `rootfs/home/x/.gitconfig` 里 `[user]` 的 name/email 注释掉并开
  `useConfigOnly = true`（镜像不含身份，误配时 commit 直接报错），本服务幂等跑 `git config --global` 写入
  `user.name`/`user.email`。
- **`home-init`**（以 `x` 线性执行，日志 `/var/log/home-init.log`）：`sudo chown` 五个 IDE home 目录，无条件
  生成或复用 deploy key（`/home/x/.ssh/repo_id_ed25519`，私钥不出容器，控制面只读公钥；所有场景都生成，无
  `CODESPACE_WORKSPACE_TYPE` 门控），随后扩展播种、docker scene dotfiles、agent playbook 与 user rules。IDE
  home 目录在 container 创建时已由控制面挂载，无需 boot 时替换。oneshot 成功即视为 home 就绪，任一步失败即非零
  退出、oneshot 失败。
- **`rclone-webdav`**、**`copyparty-webdav`**（longrun，依赖 `workspace-init`，以 `x` 分别监听 8004、8005，
  地址复用 `SSHD_BIND`）：根目录均只含 `/workspace`（只读复用容器内 `/workspace`）和 `/upload`（`5230:5230`
  可读写）。`/upload`、`/cache` 均为按实例 bind 的宿主目录，跨 stop/start 与重建保留，仅 purge 时丢失，无 quota
  或备份；`/cache` 下五个 IDE 子目录不经 WebDAV 暴露。两服务关闭归档、索引、缩略图、媒体处理、分享、
  管理/状态接口、跨站 CORS、服务发现及 FTP/FTPS/SFTP/TFTP，`rclone` 另关 HTML 目录页，`copyparty` 关
  HTML/脚本渲染及所有可关的 Web UI 扩展。服务匿名访问、镜像不提供 TLS；bridge 模式需在 workspace
  `published_ports` 显式发布端口，跨不可信网络必须在外层加 TLS、认证与访问控制。`/workspace` 含 dotfiles，
  WebDAV 读取者可见其敏感内容；两进程不共享 WebDAV `LOCK`，不得经 8004/8005 并发改同一 `/upload` 文件。
- **`supercronic`**（longrun）：监督守护并加载 `rootfs/etc/supercronic/crontab`；该 crontab 目前**有意留空**
  （零 job），加任务写 5 字段（无 user 列）条目。二进制经 binman（`script/binman.yaml` 的 `link`）提供，日志
  `/var/log/supercronic.log`。
- **`workspace-agent`**（uv application 于 `/opt/codespace`，Python 版本由 `.python-version` 声明，
  FastAPI/Pydantic/Uvicorn 依赖由 `pyproject.toml` 与 `uv.lock` 锁定；构建时以 `x` 跑 `uv python install` 装
  Python 3.14 后 `uv sync --locked --no-dev` 生成 `.venv`）：实现全在单文件 `workspace_agent.py`，绑定
  `agent.sock`（mode `0666`，访问边界由外层 `control/` 的 `0700` 保证），提供 `GET /status`、`GET /git-state`。
  控制面创建容器时固定注入 `CODESPACE_WORKSPACE_TYPE`、`CODESPACE_CLONE_URL`（blank 不注入）、
  `CODESPACE_CLONE_PATH`、`CODESPACE_OPEN_PATH`，这些保留变量不得被用户 container environment 或 env secret
  覆盖。agent 启动即在后台线程 in-process bootstrap：`repo` 先等 `control/provider-ready`（控制面注册 deploy
  key 后创建），`repo`/`git` 调 `/opt/codespace/bin/git-checkout` 幂等 clone，最后建 open path；bootstrap
  状态仅在内存，无 on-disk marker，`/status` 直读该状态并附 deploy public key。子进程一律以 `5230:5230`、
  `HOME=/home/x` 执行；动态 Git state 由 agent 直接调 Git 计算，空仓通过 `HEAD` 判断。修改命令、环境变量或 HTTP
  contract 时必须同步 Bats、agent 测试与控制面。

`/opt/codespace/bin/` 下四个 helper（`workspace-init`、`home-init`、`git-checkout`、`seed-vscode-extensions`）
由 s6 启动流程或 agent 调用，不依赖 controller 是否在线。

镜像内固定的 sshd ed25519 host key（`rootfs/etc/ssh/ssh_host_ed25519_key.pub`）由控制面 pin 在
`~/.ssh/codespace/known_hosts/codespace`；改镜像 host key 必须同步更新该 asset，详见
[`controller/DESIGN.md`](../../controller/DESIGN.md#host-数据布局)。

网络：`network_mode: host` 容器 sshd 绑 `127.0.0.1`；`network_mode: bridge` 容器 sshd 注入
`SSHD_BIND=0.0.0.0`，SSH 端口发布到 loopback `127.0.0.1:<ssh_port>` 复用 ProxyCommand 路径，workspace
`published_ports` 声明的业务端口经 gvproxy 转发到 macOS `localhost:<local>`。

## 构建

```bash
images/dev/build.sh    # 仓库根本地构建，不发布；发布由 .github/workflows/ 管理
task check             # 含 helper 的 shfmt、ShellCheck 与 Bats
```

`task sync` 同步控制面和 workspace agent 两个 uv 环境；`task lock:check` 同时校验两份 `uv.lock`。

## 变更规则

- 不修改与任务无关的 s6、Atuin client、Ollama、home-init、sshd。
- 仅供运行时使用的文件放 `rootfs/`；跨场景 home 配置也放 `rootfs/home/x/`（经 `COPY rootfs/ /` 烤入 `$HOME`）。
  `dotfiles/` 只保留非容器场景专属配置与容器运行期才落位的模板。
- 修改镜像 host contract、sshd 绑定行为或 WebDAV 服务时，同步更新本文与
  [`controller/AGENTS.md`](../../controller/AGENTS.md) 及 [`controller/DESIGN.md`](../../controller/DESIGN.md)
  中依赖这些契约的章节。
