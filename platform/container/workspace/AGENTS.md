# Workspace Image 约束

`platform/container/workspace/` 构建可独立使用、也可由 codespace control plane
管理的开发 Workspace 镜像。运行流程见 [`DESIGN.md`](DESIGN.md)，平台公共约束见
[`../AGENTS.md`](../AGENTS.md)。

## 目录职责

| 路径             | 职责                                                 |
| ---------------- | ---------------------------------------------------- |
| `Dockerfile`     | 组装工具链、复用必要配置片段、安装 Agent 与 s6       |
| `agent/`         | 独立锁定的 Python 3.14 Workspace Agent               |
| `config/`        | binman package 与 remote extension 构建清单           |
| `rootfs/`        | Workspace 系统、home、s6 service 与 runtime helper   |
| `scripts/`       | 构建期配置和安装脚本                                 |
| `tests/`         | runtime helper 的 Bats 行为测试                      |
| `agent-rules.md` | 烤入镜像并播种到 IDE 持久目录的 Agent rules          |

s6 skeleton 位于 `rootfs/etc/s6/skel/`，安装器位于
`scripts/install-s6.sh`。Service image 只能复用这两个明确入口，不得引用其他
Workspace 私有实现。

## Image Contract

- 镜像为 `ghcr.io/curoky/codespace:workspace-<distro><version>`，默认
  `workspace-debian13`。构建 context 固定为仓库根。
- 开发用户固定为 `x`（uid/gid `5230:5230`）。镜像提供 `/workspace`、
  `/workspace.enc`、`/upload`、`/cache` 与 `/run/codespace-control` 的 mount
  target。
- 运行资产只放在 `/opt/codespace/{agent,bin,share}`。镜像不包含仓库 checkout，
  不创建源码软链，也不依赖固定 host checkout 路径。
- Workspace 专属用户配置位于 `rootfs/home/x/`，不移动或镜像到 `dotfiles/`。
  可复用的 zsh 片段、用户命令及 editor 配置由 Dockerfile 显式选择；被持久 IDE
  mount 遮蔽的 Trae 和 remote settings 先放入 `/opt/codespace/share`，再由
  `init-home` 播种。
- `/run/s6/container_environment` 只允许 root 与 group `5230` 读取。

## Runtime Contract

`default` bundle 包含所有 Workspace service：

- `workspace-init`：以 `x` 执行 `/opt/codespace/bin/init-workspace`，完成数据目录
  ownership 与可选 gocryptfs mount；`sshd` 和两个 WebDAV service 依赖它。
- `home-init`：以 `x` 执行 `/opt/codespace/bin/init-home`，准备五个持久 IDE
  home mount、deploy key、editor extensions、runtime templates 和 Agent rules；
  `workspace-agent` 依赖它。
- `git-config`：幂等写入当前固定 Git identity。
- `workspace-agent`：执行 `/opt/codespace/agent/agent.py`；未注入
  `CODESPACE_SOURCE_TYPE` 时空转，通用 `podman run`、devcontainer 与 WSL 不会
  bootstrap 或监听 UDS。
- `sshd`、`rclone-webdav`、`copyparty-webdav`、`atuin-login`、
  `atuin-daemon`、`ollama`、`supercronic` 保留现有服务行为。

控制面保留环境变量为：

| 变量                      | 含义                                 |
| ------------------------- | ------------------------------------ |
| `CODESPACE_SOURCE_TYPE`   | `github`、`gitlab`、`git` 或 `empty` |
| `CODESPACE_CLONE_URL`     | 非 empty source 的 clone URL         |
| `CODESPACE_CHECKOUT_PATH` | checkout target                      |
| `CODESPACE_OPEN_PATH`     | editor open path                     |
| `CODESPACE_WORKSPACE_KEY` | 注入即启用 gocryptfs                 |

这些变量不能被 Project container environment 或 env secret 覆盖。

## Security

- deploy private key `/home/x/.ssh/repo_id_ed25519` 只在 Workspace 内生成；Agent
  仅向 control plane 返回 GitHub/GitLab source 对应的 public key。
- SSH provider host key 必须预置在 `rootfs/home/x/.ssh/known_hosts`；
  `StrictHostKeyChecking yes` 不得放宽。
- Agent 只监听 `/run/codespace-control/agent.sock`。socket mode 为 `0666`，
  外层 control mount 必须保持 owner `x`、mode `0700`，且只能经 OpenSSH
  StreamLocal forwarding 访问。
- sshd 默认绑定 `127.0.0.1`；仅 bridge 或 WSL 场景显式注入
  `SSHD_BIND=0.0.0.0`。
- Workspace encryption 依赖 `/dev/fuse`、gocryptfs 与
  `CODESPACE_WORKSPACE_KEY`。未注入 key 时 `/workspace` 必须保持 plaintext
  bind，不得隐式创建或迁移密文。

## 验证

```bash
shellcheck platform/container/workspace/scripts/install-s6.sh \
  platform/container/workspace/build.sh \
  platform/container/workspace/scripts/*.sh \
  platform/container/workspace/rootfs/opt/codespace/bin/*
bats platform/container/workspace/tests
platform/container/workspace/build.sh
```

修改环境变量、helper、s6 dependency、Agent HTTP response 或 mount 语义时，必须
同步 `DESIGN.md`、对应 Bats 测试和 control plane 调用方。
