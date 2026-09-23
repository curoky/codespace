# Workspace Image

此目录拥有 Workspace OCI image、resource payload、rootfs、embedded Agent 与 s6 graph。

## Build

- 默认 image：`platform/container/workspace/build.sh [base-image]`。
- resource image：`platform/container/workspace/build.sh --resource`。
- 修改 filesystem、权限、s6 graph 或 runtime helper 后，至少构建对应 image。

## Runtime Contract

- 固定用户是 `x`（UID/GID `5230`）；image-owned 文件位于 root-owned `/usr/local` 或
  `/etc`，`/opt` 由 `x` 管理。
- PID 1 是 `/etc/s6/init/bin/init`；service graph 只在 image build 时编译。依赖
  `/workspace` 的 service 必须依赖 `gocryptfs-workspace`，不得在运行期重跑 init 或
  oneshot。
- `/workspace`、`/workspace.enc`、IDE cache、`/run/codespace-control` 与
  `/opt/podman/data` 是外部状态边界；初始化只修正挂载根，不递归改写持久数据。
- Workspace 由 control plane 创建。`CODESPACE_ENCRYPTED` 必须为 `true` 或 `false`；
  root password 和 encryption key 只通过 `/run/secrets/*` 注入。
- Workspace service 默认只监听 loopback；Host publication 只由 Project
  `tunnel_ports` 声明。

## Resource Payload

- `resource.Dockerfile` 只承载启动无依赖的大型工具；payload 根固定为 `/opt/resource`，
  由 `codespace-resource` volume 只读挂载。
- Workspace image 只创建指向 payload 的 symlink。当前 payload 包括 Rust、CUDA、NVIDIA
  tools、radare2、rizin 与 `/usr/local/profile/go`；未挂载 volume 时允许链接悬空，s6
  service 不得依赖这些工具。

## Rootless Podman

- 内置 Podman 只服务用户 `x`，固定连接
  `unix:///run/user/5230/podman/podman.sock`；不得连接 Host rootful Podman。
- `/opt/podman/data` 可持久化但不能被多个运行中的 Workspace 共享。保留 subordinate
  IDs、setuid `newuidmap`/`newgidmap`、`SYS_ADMIN`、unconfined seccomp 与无限 pids。
- 新 data 按 backing filesystem 选择 overlay 或 VFS；已有 graphroot 沿用原 driver，
  不自动迁移或删除。内部 container 固定 `cgroups = "disabled"`。
- WSL 继承相关文件，但其 s6 bundle 不启动 `podman`；WSL 支持必须单独设计和验证。
