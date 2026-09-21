# Workspace Image

此目录独立拥有 Workspace OCI image 的构建、rootfs 和 s6 service graph。跨目录架构仍以
仓库根 `DESIGN.md` 为准。

## Build And Validation

默认构建 Debian 13 image：

```bash
platform/container/workspace/build.sh
```

指定 base image 或附加 Docker build 参数：

```bash
platform/container/workspace/build.sh ubuntu:26.04 --no-cache
```

构建脚本要求 base image 带 tag，并生成
`ghcr.io/curoky/codespace:workspace-<base>-<tag>`。提交前同时运行仓库级验证：

```bash
task check
task check:full
```

## Runtime Contract

- 固定用户是 `x`，UID/GID 都是 `5230`；不要让运行期逻辑依赖 Host 用户名。
- PID 1 是 `/etc/s6/init/bin/init`。service source 位于 `rootfs/etc/s6/s6-rc.d/`，
  image build 期间由 `scripts/install-s6.sh` 编译，运行期不重新编译。
- `/opt` 由 `x` 管理；Workspace image 自有文件位于 root-owned `/usr/local/codespace`，
  其他 image-owned executable 和配置放在 `/usr/local`、`/etc`。
- `/workspace`、`/workspace.enc`、IDE cache 和
  `/run/codespace-control` 是外部状态边界。启动脚本可以修正挂载点权限，但不能递归
  改写未知持久数据。
- Workspace 内服务默认只监听 loopback；只有 Project `tunnel_ports` 中声明的端口才能
  由控制面转发。容器之间使用 Host Podman network DNS，不使用动态 IP。
- `config/binman.yaml` 中的 image package 全部安装到 root-owned `/usr/local`。`x` 的
  `~/.local/bin/bm` 固定使用 `~/.local` prefix，供运行期把用户工具安装到 `~/.local`（binary
  在 `~/.local/bin`、store 在 `~/.local/store`）并覆盖预装版本；image service 使用
  `/usr/local/store` 的固定路径，不依赖用户可写的 `~/.local`。只被一个组件使用、且需要
  独立目录语义的软件不要链接进这两个 prefix。

Workspace 应由 Codespace control plane 按根目录 `config.example.yaml` 的 Project container
配置创建，不把手写 `podman run` 命令作为部署接口。至少保留 `CODESPACE_ENCRYPTED`、
业务数据与 control socket mount，并在 Project container 配置中显式挂载 root-owned、mode
`0400` 的 `codespace_root_password` secret；加密模式还必须挂载
`codespace_workspace_key` secret。
SSH 与 HTTP 入口由控制面分配和转发，不在 image 上声明固定 Host publication。

关键输入与状态目录：

| Interface | Contract |
| --- | --- |
| `CODESPACE_ENCRYPTED` | 必填，取值 `true` 或 `false`；决定是否解密挂载 `/workspace` |
| `/workspace.enc` | encrypted Project 的密文持久目录 |
| `/workspace` | plaintext Project 的持久目录，或 encrypted Project 的 FUSE 明文视图 |
| `/run/codespace-control` | Host 与 Workspace Agent 之间的 Unix socket 目录 |
| `/opt/podman/data` | 可选持久化的内部 Podman images、containers、volumes 与 auth |
| `/run/secrets/*` | Podman secret mount；只读取任务需要的 secret |

进入 Workspace 后可用 `s6-svstat /run/service/<service>` 查看服务状态，日志统一位于
`/var/log/s6.<service>.log`。`/workspace` 由 longrun `gocryptfs-workspace` 提供：加密模式挂载
gocryptfs、明文模式用 `s6-pause` 常驻，两种模式都会向 s6 通知就绪，依赖 `/workspace` 的
service 统一以它为前置。不要在容器中再次运行 init、s6 oneshot 或已有 longrun。

## Rootless Podman

Workspace 内置 Podman 用于开发任务中的 container build/run；它不暴露 Host rootful
Podman，也不读取 `/run/podman/podman.sock`。CLI 固定连接
`unix:///run/user/5230/podman/podman.sock`，s6 service 名为 `podman`。
`docker` 是同一 wrapper 的别名。常规使用直接执行 `podman build`、`podman run` 或对应
的 `docker` 命令，不设置 `CONTAINER_HOST`、`CONTAINER_CONNECTION` 或 `DOCKER_HOST`。
例如：

```bash
podman info --format 'rootless={{.Host.Security.Rootless}} driver={{.Store.GraphDriverName}}'
podman build -t local/app:dev .
podman run --rm local/app:dev
```

`podman5-rootless` 由共享 `config/binman.yaml` 标准安装到 `/usr/local`，与其他 image package
一样由 root 拥有。Workspace 的 client/service wrapper 位于 `/usr/local/bin`，配置位于
`/etc/containers`；持久化运行数据、用户 home 与 auth 位于 `/opt/podman/data`，network
state 位于不持久化的 `/opt/podman/network`。包内 `install.sh`、s6 模板与 CA 文件不会被调用；Podman 使用系统 CA。

外层 Workspace container 必须保留以下运行条件：

- `/etc/subuid` 与 `/etc/subgid` 为 `x` 分配 subordinate ID。
- `/usr/local/bin/newuidmap` 与 `/usr/local/bin/newgidmap` 指向 root-owned、mode `4755` 的
  BM package executable。
- 默认 Project container 配置保留 `SYS_ADMIN`、`seccomp=unconfined` 和无限
  `pids_limit`。这些是当前 nested rootless runtime contract，不应在未完成 image build
  和真实 container 验证前删除。

Podman 状态位于 `/opt/podman/data`。推荐在 Project volume 中持久化：

```yaml
project_defaults:
  container:
    volumes:
      - ${RESOURCE_DATA}/podman:/opt/podman/data
```

s6 启动时只把 data 挂载根目录修正为 `5230:5230`、mode `0700`，绝不递归 chown；graphroot
中的 subordinate UID/GID 必须原样保留。若 Host path 不允许 container root chown，需在
Host 上提前赋予 UID/GID `5230`。不要在多个同时运行的 Workspace 间共享同一 data
目录。

全新 data 首次启动时，`podman-server` 检查 backing filesystem：ext2/3/4、XFS、Btrfs
使用 native overlay，其余类型（包括外层 overlayfs、NFS 与 FUSE）使用 VFS。已有 data
根据 `vfs-images` 或 `overlay-images` 沿用原 driver。Podman 不迁移 graphroot；更换
filesystem 或 driver 时应使用新的空 data 目录。两类 storage 同时存在会直接拒绝启动，
避免误读数据。

当前外层 container 没有向内层委派 cgroup controller，因此内部 container 固定
`cgroups = "disabled"`。这是资源隔离限制：内部 workload 共用 Workspace 的外层资源
边界，不能依赖内部 Podman cgroup limit。

常用检查：

```bash
s6-svstat /run/service/podman
tail -n 200 /var/log/s6.podman.log
podman info --format 'rootless={{.Host.Security.Rootless}} driver={{.Store.GraphDriverName}}'
podman run --rm docker.io/library/busybox:1.37 true
```

socket 不存在时先检查 s6 状态和日志。storage driver 报错时检查 data root 的实际
filesystem，以及该目录是否已有另一 driver 创建的 graphroot；不要通过删除用户数据
来自动恢复。

WSL image 会继承 Podman binary、配置和 `/opt/podman/data`，但 WSL 使用自己的 `wsl` s6
bundle，默认不启动 `podman` service。若要在 WSL 支持它，应作为 WSL platform 能力单独
设计和验证，不能只把 `podman` 加入 `wsl/contents.d`。
