# Workspace Image

此目录拥有交互式 Workspace OCI image、只读 resource payload、rootfs、内嵌 Agent 和完整 s6
graph。控制面决定实例配置；image 定义容器内固定 filesystem 与启动契约。

## Context Map

- `Dockerfile`、`rootfs/`、`scripts/` 和 `config/binman.yaml`：主 Workspace image。
- `resource.Dockerfile` 与 `config/binman-resource.yaml`：独立的大型工具 payload。
- `agent/AGENTS.md`：容器内 bootstrap/Git HTTP Agent。
- `tools/java-tool/AGENTS.md`、`tools/node-tool/AGENTS.md`：resource build 与 Workspace 运行期
  共用的 installer。
- `rootfs/home/x/.codex/skills/`：按任务加载的容器使用 skill；`.trae/skills` 与
  `.trae-cn/skills` 分别为每个内置 skill 创建链接。工具、GitHub、Podman 或 s6 的使用约定
  变化时同步更新对应 skill。它们不替代本维护文档。

## Build

```bash
platform/container/workspace/build.sh [base-image]
platform/container/workspace/build.sh --resource
```

主 image 的 filesystem、权限、s6 graph、Agent 或 runtime helper 变化时构建主 image；payload
内容、symlink target 或 installer 变化时构建 resource image。两侧 contract 同时变化时都构建。

## Runtime Contract

- 交互用户是 `x`（UID/GID `5230`）。image-owned system 文件位于 root-owned `/usr/local`、
  `/opt/codespace`、`/opt/podman`、`/etc` 或只读 resource payload；普通 runtime 软件安装到
  用户 Nix profile，Java/Node CLI 分别由专用 installer 写入 `/opt/java/tools`、
  `/opt/node/tools`。不要在启动时重建 immutable image 内容。
- PID 1 是 `/etc/s6/init/bin/init`，service graph 只在 image build 时编译。依赖
  `/workspace` 的 service 必须依赖 `gocryptfs-workspace`；runtime 不重跑 graph compile 或
  image-build oneshot。
- 加密 Workspace 的 `/workspace.enc` 由 Host bind 提供，Host 与容器内都保持
  `5230:5230`；gocryptfs 以 `x` 运行，并通过 `allow_other` 提供明文读写视图。
- `/workspace`、`/workspace.enc`、IDE cache、`/run/codespace-control` 和
  `/opt/podman/data` 是外部状态边界。初始化只准备挂载根，不能递归 chown、迁移或清除已有
  持久数据。
- `CODESPACE_ENCRYPTED` 只能是 `true`/`false`。root password、workspace key 和其他
  credential 只从 `/run/secrets/*` 读取；缺失必要 secret 必须 fail-fast。
- root password 使用 SHA-512 hash 配合静态 sudo contract；`su` 保留发行版的 setuid
  implementation，不用 standalone shadow 替换。
- Workspace 内 service 默认监听 container loopback。Host publication 与 UI tunnel allowlist
  只由控制面 Project config 决定。
- Atuin client 使用官方 sync；login credential 格式和 login service 由当前 s6 script 定义。
  未加入 default bundle 的 server definition 不应被其他 service 当作依赖。

## Resource Payload

- payload 根固定为 `/opt/resource`，通过 `codespace-resource` named volume 只读挂载。主 image
  自带运行所需的 Python 3.14 与 uv tools；resource 提供其余 Python runtime 和可选 uv
  tools，并通过 `/opt/resource/opt/uv/bin` 直接加入 PATH。binman 的默认 launcher 与 store
  必须一起保留在 `/opt/resource/usr/local/{bin,store}`，由 resource bin PATH 统一暴露，不在主
  image 为单个 package 建兼容链接。Java/Node 额外拆成只读 runtime 子目录链接加可写
  `/opt/java/tools`、`/opt/node/tools`。未挂载时允许 resource 链接悬空，默认 s6 service
  不得依赖 resource-only 内容。
- `resource.Dockerfile` 是工具、版本、URL、checksum 和安装方式的 source of truth。不要在
  `AGENTS.md` 维护重复清单，也不要从主 image 的其他 package manager 重复安装同名工具。
- 多版本 family 保留版本目录；默认选择由 profile/PATH 显式声明。launcher 不能依赖 payload
  内部 content-addressed store 的易变路径。
- Java/Node CLI 通过各自通用 installer 隔离安装，并永久绑定 resource image 选定的外部
  runtime。launcher 相对自身定位同一 tools root 下的 env，因此整个 Java/Node family 可从
  build stage 搬到 resource payload；运行期增量安装只写入 `/opt/java/tools`、
  `/opt/node/tools`。package-specific metadata 留在 `resource.Dockerfile`。
- Workspace helper 固定位于 `/opt/codespace`，Podman wrapper 固定位于 `/opt/podman/bin`；不保留
  对应的 `/usr/local` 兼容路径。

## Rootless Podman

- 内置 Podman 只服务用户 `x`，固定使用
  `unix:///run/user/5230/podman/podman.sock`；它不能连接或管理 Host rootful Podman。
- `/opt/podman/data` 是唯一持久状态边界，不能由多个运行中的 Workspace 共享。保留 rootless
  所需 subordinate IDs、setuid helper、capability/security 与 unlimited pids contract。
- 全新 graphroot 根据 backing filesystem 选择 native overlay 或 VFS；已有 graphroot 沿用
  原 driver，不自动迁移、重建或删除。内部 container 固定禁用 cgroups。
- WSL 继承 filesystem，但使用独立 s6 bundle且不启动 Podman；涉及 inherited graph 时按
  `platform/wsl/AGENTS.md` 追加验证。
