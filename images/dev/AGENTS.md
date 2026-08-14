# 开发镜像约束

`images/dev/` 构建 Codespace 基础与参考开发镜像。它组合 `/opt/sb` 静态工具、
Nix、Rust、Java、Node.js、Go、uv、Conda、dotfiles 和自建 s6 init。

本文是开发镜像结构、s6 init、容器 SSH 契约与镜像必须提供的 host contract 的事实来源。仓库整体
架构与跨组件契约见仓库根 [`AGENTS.md`](../../AGENTS.md)；消费该镜像的控制面契约见
[`controller/AGENTS.md`](../../controller/AGENTS.md)，host 级共享服务镜像见
[`images/sidecar/AGENTS.md`](../sidecar/AGENTS.md)。容器内工具路径与使用方式见
[`dev-environment.md`](dev-environment.md)。修改开发镜像契约时，必须在同一变更中同步更新本文。

## 目录

| 路径 | 职责 |
| --- | --- |
| `Dockerfile` | 组装静态工具、Nix、各语言运行时、dotfiles 和自建 s6 init |
| `build.sh` | 从仓库根目录构建本地开发镜像 |
| `script/` | 镜像构建脚本，含 `setup-s6.sh`、`setup-vscode-extensions.sh`（构建期装扩展）、`seed-vscode-extensions.sh`（启动期播种） |
| `rootfs/` | 烤进镜像的文件（s6 bundle、sshd、容器 SSH config 与 host key 等） |
| `dev-environment.md` | 容器内工具链路径与使用方式 |

## s6 init

开发镜像不使用 s6-overlay。`images/dev/script/setup-s6.sh` 从 `/opt/sb/store`
中的 s6/execline 二进制生成 `/etc/s6/init` 和 `/etc/s6/db`。

新增服务必须放入 `images/dev/rootfs/etc/s6/s6-rc.d/` 并加入相应 bundle；execline 脚本通过
`s6-envdir -Lf -- /run/s6/container_environment` 读取容器环境，该目录仅允许 root 和
`x` 读取。`workspace-init` 必须先于 `sshd` 和 `home-init` 完成，把挂载的 `/workspace`
归属到 `5230:5230`。

## 容器 SSH 契约

Container 专用 SSH config 位于 `images/dev/rootfs/home/x/.ssh/config`，
为所有目标启用 GSSAPI 认证与凭据委派；不得复用带 host 凭据代理的
`dotfiles/ssh/user.ssh_config`。GitHub/GitLab host key 固定在同目录的 `known_hosts`，
provider 连接必须使用严格校验。

## 镜像 host contract

开发镜像必须提供：

- 用户 `x`，uid/gid 为 `5230:5230`；
- 可写的 `/workspace`；
- 默认 host network，sshd 监听地址由 `SSHD_BIND` 环境变量控制，默认 `127.0.0.1`；
- Podman security option `disable` 和 `seccomp=unconfined`；
- 现有 s6 entrypoint、sshd、home-init、Atuin client、Git 和 OpenSSH client；
- s6 转储到 `/run/s6/container_environment` 的容器环境仅允许 root 和 `x` 读取；
- `workspace-init` s6 oneshot，且 `sshd` 和 `home-init` 均依赖它；
- `rclone-webdav` 和 `copyparty-webdav` s6 longrun 均依赖 `workspace-init`，以用户 `x`
  分别监听 8004 和 8005；监听地址复用 `SSHD_BIND`，host 模式默认 `127.0.0.1`，bridge 模式为
  `0.0.0.0`。两个 WebDAV 根目录均只包含 `/workspace` 和 `/upload`：前者直接复用容器内现有
  `/workspace`，但只在 WebDAV 层授予读取权限；后者是 uid/gid `5230:5230`、mode `0700` 的容器
  writable-layer 目录，允许完整 WebDAV 读写。容器内 IDE、SSH 和构建工具仍可直接写
  `/workspace`；`/upload` 在同一 container 的 stop/start 后保留，删除或重建 container 后丢失，
  不提供 quota 或备份。`rclone` 用只读 union 暴露 workspace；`copyparty` 的 `wram` volflag
  仅确认接受 writable-layer 的非持久生命周期。
- 两个 WebDAV 服务均关闭归档、索引、缩略图、媒体处理、分享、管理/状态接口、跨站 CORS、
  服务发现及 FTP/FTPS/SFTP/TFTP 等额外能力，因此不提供搜索、预览、在线压缩、分享链接、
  恢复或浏览器跨站访问。`rclone` 同时关闭 HTML 目录页；`copyparty` 的 WebDAV 与 browser
  listing/上传共用 HTTP handler，无法在进程内彻底剥离后两者，但已关闭 HTML/脚本渲染及所有
  可独立关闭的 Web UI 扩展。服务为匿名访问且镜像不提供 TLS；bridge 模式需在 project 的
  `published_ports` 中显式发布端口，跨不可信网络时必须在外层增加 TLS、认证和访问控制。
  `/workspace` 包含 dotfiles，WebDAV 读取者可看到其中的敏感内容。两个进程不共享 WebDAV
  `LOCK` 状态，不得经 8004 和 8005 并发修改同一 `/upload` 文件；
- 位于 `rootfs/home/x/.ssh/config` 的 container SSH config，为 `Host *` 启用 GSSAPI
  认证与凭据委派，并固定使用 `~/.ssh/repo_id_ed25519` 访问 GitHub 和 GitLab，构建时
  收紧为 `0600`；
- 位于同目录的 `known_hosts`，包含 GitHub/GitLab 官方发布的 host key；provider SSH
  连接必须使用 `StrictHostKeyChecking yes`，不得回退到 `accept-new`。

`network_mode: host` 的容器使用 host network，sshd 绑定 `127.0.0.1`。`network_mode: bridge`
的容器改用 bridge network：sshd 注入 `SSHD_BIND=0.0.0.0`，SSH 端口发布到 loopback
`127.0.0.1:<ssh_port>` 以复用现有 ProxyCommand 路径，project `published_ports` 声明的业务
端口发布后经 gvproxy 转发到 macOS `localhost:<local>`。

镜像内固定的 sshd ed25519 host key（`rootfs/etc/ssh/ssh_host_ed25519_key.pub`）由控制面 pin 在
`~/.ssh/codespace/known_hosts/codespace`；改镜像 host key 必须同步更新该 asset，详见
[`controller/AGENTS.md`](../../controller/AGENTS.md) 的「SSH 投影」章节。

## VSCode Remote 扩展预装

构建期由独立 stage `stage_vscode_ext` 运行 `script/setup-vscode-extensions.sh`，用官方
code-server 把 `dotfiles/vscode/extensions.txt` 里的扩展装进参考副本 `/opt/vscode-extensions`，
再由 main stage 以 `COPY --from` 取出（code-server 二进制留在构建 stage，不入 final image）。
该 stage 只依赖 `extensions.txt` 与安装脚本，和 `stage_rust`、main 的 nix/python 步骤并行构建，无关的
仓库改动不会触发扩展重装。`extensions.txt` 是扩展列表的唯一事实来源，脚本安装其中每一行、
不做二次过滤；纯客户端扩展（`extensionKind` 为 `ui` 的 `remote-ssh` 等，以及主题、图标、
keymap）由本地 IDE 安装，不写进 `extensions.txt`。

因为 `home-init.sh` 启动时把 `~/.vscode-server`、`~/.trae-server`、`~/.trae-cn-server`
软链到持久化的 `/workspace/.cache`，扩展不能烤进镜像的 `~/.vscode-server`（首启会被
`rm -rf` 清掉）。运行期 `home-init.sh` 调用 `script/seed-vscode-extensions.sh` 把参考副本
播种到这三个 server 的 `extensions/` 目录并合并 `extensions.json`（用户已装版本优先），每个
target 用 `.devspace-extensions-seeded` marker 保证只播种一次；删除该 marker 可重新播种。
参考副本路径可用 `REF_EXTENSIONS` 覆盖。Trae 与 Trae CN 复用同一份 VSCode 扩展副本。

## 构建

在仓库根目录本地构建：

```bash
images/dev/build.sh
```

本地构建不会发布镜像，发布流程由 `.github/workflows/` 管理。

## 变更规则

- 不修改 `images/dev/` 中与任务无关的 s6、Atuin client、Ollama、home-init 和 sshd。
- 仅供开发镜像运行时使用的文件放在 `rootfs/`；跨场景用户配置来源于 `dotfiles/`。
- 修改镜像 host contract、sshd 绑定行为或 WebDAV 服务时，同步更新本文与
  [`controller/AGENTS.md`](../../controller/AGENTS.md) 中依赖这些契约的章节。
