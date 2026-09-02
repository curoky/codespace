# Workspace Image Design

## Build Layout

Workspace image 使用仓库根作为 build context，但只复制声明的输入：

```mermaid
flowchart LR
    Rootfs["workspace/rootfs<br/>system + home"] --> Image
    Agent["workspace/agent"] --> Image
    Config["workspace/config<br/>build manifests"] --> Image
    Scripts["workspace/scripts"] --> Image
    Dotfiles["selected reusable config"] --> Image
    Rules["agent-rules.md"] --> Image
    Image --> Runtime["/opt/codespace/{agent,bin,share}"]
```

`rootfs/` 拥有 Workspace service、系统配置和 `home/x/` 下的镜像专属用户配置。
s6 skeleton 位于 `rootfs/etc/s6/skel/`，`scripts/install-s6.sh` 在 build 时
编译 `/etc/s6/db` 并生成 `/etc/s6/init`；Service image 只复用这两项。
Dockerfile 仅从 `dotfiles/` 选择明确复用的 zsh 片段、用户命令与 editor 配置。

## Startup

```mermaid
flowchart TD
    Init["s6-linux-init"] --> Default["default bundle"]
    Default --> WorkspaceInit["workspace-init"]
    Default --> HomeInit["home-init"]
    Default --> GitConfig["git-config"]
    WorkspaceInit --> SSHD["sshd"]
    WorkspaceInit --> WebDAV["rclone/copyparty WebDAV"]
    HomeInit --> Agent["workspace-agent"]
    Default --> Other["Atuin / Ollama / supercronic"]
```

`workspace-init` 是 Workspace 数据就绪门控。它先修正 `/workspace`、
`/workspace.enc`、`/upload` 和 `/cache` ownership；存在
`CODESPACE_WORKSPACE_KEY` 时初始化或复用 gocryptfs，再把明文挂到
`/workspace`。

`home-init` 不依赖 `workspace-init`。它准备五个持久 IDE home mount，无条件生成或
复用 deploy key，并从 `/opt/codespace/share` 播种 editor extensions、Trae
runtime 配置、remote settings、Agent playbook 和 rules。

## Agent Protocol

Workspace Agent 绑定 `/run/codespace-control/agent.sock`，提供：

| Method | Path         | Response                                            |
| ------ | ------------ | --------------------------------------------------- |
| `GET`  | `/status`    | `state`、GitHub/GitLab deploy `public_key`、`error` |
| `GET`  | `/git-state` | `unpushed`、`uncommitted`、最多 20 条 `detail`      |

未注入 `CODESPACE_SOURCE_TYPE` 时进程保持 idle，不创建 socket。受管 Workspace 的
bootstrap 流程为：

```mermaid
sequenceDiagram
    participant CP as Control Plane
    participant Agent as Workspace Agent
    participant Provider as Git Provider
    participant Git as checkout helper

    CP->>Agent: start with source/clone/checkout/open env
    alt source is github or gitlab
        Agent-->>CP: status awaiting-provider + public key
        CP->>Provider: register deploy key
        CP->>Agent: create provider-ready marker
    end
    alt source is not empty
        Agent->>Git: checkout clone-url checkout-path
        Git-->>Agent: reused or cloned checkout
    end
    Agent->>Agent: mkdir open path
    Agent-->>CP: status ready
```

`checkout` 对已有完整 Git checkout 或已标记的 empty repository 幂等；非 Git
target 必须 fail-fast，避免覆盖持久数据。`/git-state` 只在非 empty source 且
Agent ready 时可用。

## Persistent Data

control plane 将同一 Workspace 的数据映射为：

| Container path                      | Purpose                               |
| ----------------------------------- | ------------------------------------- |
| `/workspace` 或 `/workspace.enc`    | plaintext checkout 或 ciphertext root |
| `/upload`                           | WebDAV 可写交换目录                   |
| `/cache`                            | IDE 持久数据源                        |
| `/run/codespace-control`            | provider marker 与 Agent UDS          |
| `/home/x/.{vscode-server,trae,...}` | `/cache` 下五个直接 mount             |

Agent 子进程固定以 uid/gid `5230:5230`、`HOME=/home/x` 执行。provider token
不进入镜像，deploy private key 不离开 Workspace。
