# 开发镜像约束

`images/dev/` 构建 Codespace 基础与参考开发镜像，组合 `/opt/bm` 静态工具、Nix、Rust、Java、
Node.js、Go、uv、Conda、dotfiles 和自建 s6 init。

本文是开发镜像结构、s6 init、容器 SSH 契约与镜像 host contract 的事实来源。整体架构与跨组件契约见
仓库根 [`AGENTS.md`](../../AGENTS.md)；消费该镜像的控制面契约见 [`controller/AGENTS.md`](../../controller/AGENTS.md)，
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

开发镜像不使用 s6-overlay。`script/setup-s6.sh` 从 `/opt/bm/store` 的 s6/execline 二进制生成
`/etc/s6/init` 和 `/etc/s6/db`。新增服务放入 `rootfs/etc/s6/s6-rc.d/` 并加入相应 bundle；execline
脚本用 `s6-envdir -Lf -- /run/s6/container_environment` 读容器环境，该目录仅 root 和 `x` 可读。
每个 s6 服务的 `up`/`run` 只做「设置 fd/env 后 `exec` 一个 `/opt/codespace/bin/` 编排脚本」的纯壳，
具体逻辑一律在 helper 脚本里，不写进 execline。`workspace-init` 是唯一的 workspace 就绪门控 oneshot：
它以 root 调用编排脚本 `workspace-init`，先 `workspace-chown` 把挂载的 `/workspace`、
密文根 `/workspace.enc`、`/upload`、`/cache` 与五个持久化 IDE home mount 都归属到 `5230:5230`，再
`s6-setuidgid x` 调 `workspace-crypt` 在启用加密时把明文挂到 `/workspace`（详见 host contract）。
`sshd`、异步 `home-init`、`workspace-deploy-key` 和两个 WebDAV 服务都依赖 `workspace-init`；
`workspace-bootstrap` 和 `workspace-agent` 均依赖 `workspace-deploy-key`。

runlevel 分三层：`user-base` 含通用开发镜像服务，`user-final` 嵌套 `user-base`（gitconfig 已并入
`home-init` 的 `home-setup`，不再有独立 `gitconfig-init` 服务），`managed-workspace` 再嵌套
`user-final` 并加入 Controller 专用的 deploy-key、bootstrap 与 agent。`setup-s6.sh` 的
`s6-linux-init-maker -D user-final` 保持通用镜像默认 runlevel；控制面创建
environment时固定注入 `DEVSPACE_RUNLEVEL=managed-workspace`。rc.init读取
`/run/s6/container_environment/DEVSPACE_RUNLEVEL`，非空时覆盖 maker默认；运行期也可
`s6-rc -up change <bundle>` 在线切换。

## 容器 SSH 契约

Container 专用 SSH config 位于 `rootfs/home/x/.ssh/config`，为 `Host *` 启用 GSSAPI 认证与凭据委派，
并固定用 `~/.ssh/repo_id_ed25519` 访问 GitHub/GitLab，构建时收紧为 `0600`；不得复用带 host 凭据代理的
`dotfiles/ssh/user.ssh_config`。GitHub/GitLab host key 固定在同目录 `known_hosts`，provider 连接必须
`StrictHostKeyChecking yes`，不得回退到 `accept-new`。该 private key 由 `deploy-key`
在容器内生成，控制面只读取对应公钥。

控制面的 `git` 类型 workspace 直接 clone 任意内网 `git@host:owner/name.git`（或 `ssh://` 形式）URL，不注入
deploy key。此类连接的认证与 host key 校验完全由本 SSH 契约承担：内网 host 通常经 `Host *` 的 GSSAPI/Kerberos
（配合宿主 `/etc/krb5.conf` bind-mount）认证；host key 必须预置在同目录 `known_hosts`（或由该 host 的镜像/运维
资产提供），`StrictHostKeyChecking yes` 下未预置的 host 会被拒绝。新增内网 git host 需在此同步 host key。

## 镜像 host contract

开发镜像必须提供：

- 用户 `x`（uid/gid `5230:5230`）、可写的 `/workspace`、`/upload` 与 `/cache`；三者都由控制面按实例
  bind-mount `~/codespace/workspaces/<workspace>/<instance>/` 下的同名子目录，删除或重建 container 后
  各自内容按宿主目录留存/清理；同一 `cache/` 下的五个 IDE 子目录还分别直接 bind-mount 到
  `/home/x/.vscode-server`、`/home/x/.trae`、`/home/x/.trae-cn`、`/home/x/.trae-server` 与
  `/home/x/.trae-cn-server`；
- 控制面把同一 instance 的 `control/` bind-mount 到 `/run/codespace-control`。Host 目录保持 login user
  所有且 mode `0700`；不由 `workspace-init` chown；
- 默认 host network，sshd 监听地址由 `SSHD_BIND` 控制，默认 `127.0.0.1`；
- Podman security option `disable` 和 `seccomp=unconfined`；
- 现有 s6 entrypoint、sshd、home-init、Atuin client、Git 和 OpenSSH client；
- s6 转储到 `/run/s6/container_environment` 的容器环境仅 root 和 `x` 可读；
- `workspace-init` s6 oneshot 是唯一 workspace 就绪门控，`up` 只 `exec` 编排脚本
  `/opt/codespace/bin/workspace-init`（以 root 起）；`sshd`、`home-init`、`workspace-deploy-key`
  与两个 WebDAV 服务依赖它，`workspace-bootstrap` 与 `workspace-agent` 再依赖 `workspace-deploy-key`。
  编排脚本先以 root 跑 `workspace-chown`，把挂载的 `/workspace`、`/workspace.enc`、`/upload`、
  `/cache` 与五个 IDE home目录都 `chown` 为 `5230:5230`（数据 mount 均由控制面按实例 bind 宿主目录，
  rootful Podman直接透传所有权），再 `s6-setuidgid x` 调 `workspace-crypt` 完成加密挂载。
  该 crypt helper 以容器环境变量 `WORKSPACE_CRYPT_KEY` 是否注入为信号自适应（对齐控制面 workspace 的
  `encrypt_workspace`）：未注入则跳过、`/workspace` 保持明文 bind；注入则用 gocryptfs（`/opt/bm/bin/gocryptfs`）
  把密文根 `/workspace.enc`（host bind 落盘处）解密挂到 `/workspace`，密文根缺 `gocryptfs.conf` 时先 `-init`。
  gocryptfs 依赖 FUSE：容器须有 `/dev/fuse` 与 `SYS_ADMIN`（或 security option `disable`），镜像预置
  `/etc/fuse.conf` 的 `user_allow_other` 以支持 `-allow_other`（sshd/WebDAV 等其他用户访问明文）。
  gocryptfs（binman `gocryptfs`）自身不带 fusermount，挂载时经 PATH 调用它（go-fuse 优先 `fusermount3`
  再回退 `fusermount`），故 binman `link` 另装 `fuse3` 提供 `/opt/bm/bin/fusermount3`；缺它挂载会以
  `fs.Mount failed: exec: "…fusermount…": no such file or directory` 失败，连带 sshd 不起。
  crypt 经 `s6-setuidgid x` 降权后挂载，`x` 无 CAP_SYS_ADMIN，故 `setup-sysconf.sh` 构建期给
  `fusermount3` 加 setuid root（binman 静态包默认不带该位）；缺 setuid 会以 `fusermount3: mount failed:
  Operation not permitted` 失败。日志写 `/var/log/workspace-init.log`；
- Git 全局身份由 `home-init` 的 `home-setup` 调用 `gitconfig` 写入（不再有独立
  `gitconfig-init` s6 服务）：baked `rootfs/home/x/.gitconfig` 里 `[user]` 的 name/email 注释掉
  并开 `useConfigOnly = true`（镜像不含身份，误配时 commit 直接报错），`gitconfig` 幂等跑
  `git config --global` 写入 `user.name`/`user.email`；
- `home-init` 是受监督 longrun，依赖 `workspace-init`，异步执行扩展播种、gitconfig、docker scene dotfiles、
  agent playbook与 user rules初始化（`home-init` 管理 marker，降权后调用 `home-setup`
  执行实际编排）；五个 IDE home目录在 container创建时已由控制面直接挂载，不需 boot
  时替换目录。`home-init` 完成或失败后保持运行，managed模式分别写
  `control/home.ready`、`control/home.failed`，通用镜像模式不写 control marker；
- `rclone-webdav` 和 `copyparty-webdav` s6 longrun 均依赖 `workspace-init`，以用户 `x` 分别监听 8004、8005；
  监听地址复用 `SSHD_BIND`（host 默认 `127.0.0.1`，bridge 为 `0.0.0.0`）。两者根目录均只含 `/workspace`
  （复用容器内 `/workspace`，WebDAV 层只读）和 `/upload`（uid/gid `5230:5230` 的 writable 目录，允许完整读写）。
  `/upload` 由控制面按实例 bind 宿主目录，跨 container stop/start 与重建都保留，仅 purge 删除该实例宿主目录时
  丢失，无 quota 或备份。`/cache` 同为按实例 bind 的宿主目录，用于构建/工具缓存；其下五个 IDE 子目录
  同时直接挂载到对应 home路径以持久化 IDE 远端 server 与配置，但不经 WebDAV 暴露。
  `rclone` 只读暴露 workspace；
- 两个 WebDAV 服务均关闭归档、索引、缩略图、媒体处理、分享、管理/状态接口、跨站 CORS、服务发现及
  FTP/FTPS/SFTP/TFTP，`rclone` 另关 HTML 目录页、`copyparty` 关 HTML/脚本渲染及所有可独立关闭的 Web UI 扩展。
  服务匿名访问、镜像不提供 TLS；bridge 模式需在 workspace `published_ports` 显式发布端口，跨不可信网络必须在外层加 TLS、认证与访问控制。
  `/workspace` 含 dotfiles，WebDAV 读取者可见其中敏感内容。两个进程不共享 WebDAV `LOCK`，不得经 8004/8005
  并发修改同一 `/upload` 文件；
- `supercronic` s6 longrun，监督守护进程并加载 `rootfs/etc/supercronic/crontab`；该 crontab 目前**有意留空**
  （零 job）。加任务写 5 字段（无 user 列）条目。二进制经 binman
  （`script/binman.yaml` 的 `link`）提供，日志写 `/var/log/supercronic.log`；
- `workspace-deploy-key` s6 oneshot对 repo、git、blank workspace一律以用户 `x` 执行
  `/opt/codespace/bin/deploy-key`，在 `/home/x/.ssh/` 生成或复用 deploy keypair；
  private key不离开容器。该服务与 bootstrap、agent仅属于 `managed-workspace` bundle。控制面创建容器时
  固定注入 `DEVSPACE_RUNLEVEL=managed-workspace`、`CODESPACE_WORKSPACE_TYPE`、
  `CODESPACE_CLONE_URL`（blank不注入）、`CODESPACE_CLONE_PATH` 和 `CODESPACE_OPEN_PATH`；这些保留变量
  不得被用户 container environment或 env secret覆盖。`workspace-bootstrap` s6 longrun执行
  `/opt/codespace/bin/workspace-bootstrap`：repo等待 `control/provider-ready`，git直接继续，
  blank跳过 checkout，随后调用 checkout/open-path helper；成功写 `control/bootstrap.ready`，失败写
  `control/bootstrap.failed`，然后以 `s6-pause` 保持运行而不阻塞 s6-rc事务。helper以 `5230:5230`、
  `HOME=/home/x` 执行实际 workspace命令；同一 container重启时复用已有 ready marker；
- `workspace-agent` 使用 `/opt/codespace` 下的独立 uv application，Python版本由 `.python-version` 声明，
  FastAPI、Pydantic、Uvicorn依赖由同目录 `pyproject.toml` 与 `uv.lock` 锁定；镜像先以用户 `x` 执行
  `uv python install` 安装 Python 3.14，再复用该 uv-managed Python执行 `uv sync --locked --no-dev`
  生成 `.venv`。实现全部位于单文件 `workspace_agent.py`，清理并绑定 `agent.sock`，仅提供
  `GET /status`、`GET /git-state`；
  socket 本身 mode `0666`，访问边界由外层 `control/` 的 `0700` 权限保证。`/status` 从 bootstrap marker
  与 home-init marker聚合状态，并读取 deploy public key；控制面注册 deploy key后直接在 host control目录
  创建 `provider-ready` marker。控制面每次创建 container前清空旧 marker，同一 container重启则复用 marker
  保持幂等；agent Git查询子进程以 `5230:5230`、`HOME=/home/x` 执行；
- `/opt/codespace/bin/` 下十个 runtime helper 均由 s6启动流程执行，不依赖 controller是否调用；s6 只保留
  少量任务，每个任务的 `up`/`run` 是纯壳，`exec` 到对应编排脚本，编排脚本再按序调用单一职责小脚本：
  `workspace-init`（`workspace-init` oneshot 入口，root）依次调 `workspace-chown`
  （chown workspace mount）与降权后的 `workspace-crypt`（初始化/挂载加密 workspace）；
  `deploy-key`（`workspace-deploy-key` oneshot 入口）无条件生成或复用 deploy private key；
  `workspace-bootstrap`（`workspace-bootstrap` longrun 入口）按容器环境编排 workspace初始化，
  内联创建 editor open path，并调 `git-checkout` 执行幂等 clone；
  `home-init`（`home-init` longrun 入口）编排耗时 home初始化并发布 managed状态，降权后调用
  `home-setup`，后者顺序调用 `seed-vscode-extensions`（播种构建期扩展副本到各 IDE
  server）、`gitconfig`（写 Git 全局身份）、dotfiles、agent playbook 与 user rules。
  动态 Git state由 agent直接调用 Git计算，空仓通过 `HEAD` 判断，不依赖 checkout marker。
  修改命令、环境变量或 HTTP contract 时必须同步 Bats、agent测试与控制面。

网络：`network_mode: host` 容器 sshd 绑 `127.0.0.1`。`network_mode: bridge` 容器 sshd 注入
`SSHD_BIND=0.0.0.0`，SSH 端口发布到 loopback `127.0.0.1:<ssh_port>` 复用 ProxyCommand 路径，workspace
`published_ports` 声明的业务端口经 gvproxy 转发到 macOS `localhost:<local>`。

镜像内固定的 sshd ed25519 host key（`rootfs/etc/ssh/ssh_host_ed25519_key.pub`）由控制面 pin 在
`~/.ssh/codespace/known_hosts/codespace`；改镜像 host key 必须同步更新该 asset，详见
[`controller/DESIGN.md`](../../controller/DESIGN.md#host-数据布局)。

## 构建

```bash
images/dev/build.sh    # 仓库根本地构建，不发布；发布由 .github/workflows/ 管理
task check             # 含 helper 的 shfmt、ShellCheck 与 Bats
```

`task sync` 同步控制面和 workspace agent 两个 uv环境；`task lock:check` 同时校验两份 `uv.lock`。

## 变更规则

- 不修改与任务无关的 s6、Atuin client、Ollama、home-init、sshd。
- 仅供运行时使用的文件放 `rootfs/`；跨场景 home 配置也放 `rootfs/home/x/`（经 `COPY rootfs/ /` 烤入 `$HOME`，
  无需构建期 `setup.sh`）。`dotfiles/` 只保留非容器场景专属配置与容器运行期才落位的模板。
- 修改镜像 host contract、sshd 绑定行为或 WebDAV 服务时，同步更新本文与
  [`controller/AGENTS.md`](../../controller/AGENTS.md) 及
  [`controller/DESIGN.md`](../../controller/DESIGN.md) 中依赖这些契约的章节。
