# Workspace Image Design

## Build Layout

Workspace image 使用仓库根作为 build context，但只复制声明的输入：

```mermaid
flowchart LR
    Rootfs["workspace/rootfs<br/>system + home"] --> Image
    Agent["workspace/agent"] --> Image
    Config["workspace/config<br/>build manifests"] --> Image
    Scripts["workspace/scripts"] --> Image
    Playbook["agent playbook<br/>build-time input"] --> Image
    Image --> Runtime["/opt/codespace/{agent,bin,share}"]
```

`rootfs/` 拥有 Workspace service、系统配置和 `home/x/` 下的镜像专属用户配置。
s6 skeleton 位于 `rootfs/etc/s6/skel/`，`scripts/install-s6.sh` 在 build 时
编译 `/etc/s6/db` 并生成 `/etc/s6/init`；Service image 只复用这两项。
Agent playbook 在 build 时合并到 `/home/x`。Workspace-owned home 配置只在
`rootfs/home/x/` 维护；重复的 Trae 配置、Workspace rule 与 remote settings 通过
相对软链接共享 canonical 文件，Host installer 也直接消费这棵 source tree。

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

`workspace-init` 是 Workspace 数据就绪门控。它先以 `5230:5230`、`0700` 幂等准备
Workspace data、ciphertext root、upload 和 cache。启用 encryption 时初始化或复用
gocryptfs，再把明文挂到 `/workspace`。

`home-init` 不依赖 `workspace-init`。它准备各 IDE home 下持久化的 `bin` 与
`extensions` mount，无条件生成或复用 deploy key，并从 image template 幂等播种
editor extensions。其余 Trae 配置、remote settings 与 rules 直接来自 image home，
启动时不复制。

## Agent Protocol

Workspace Agent 绑定 control UDS，对控制面暴露 readiness、deploy public key 与只读
Git state。没有受管 Workspace bootstrap 输入时进程保持 idle，不创建 socket。受管
Workspace 的 bootstrap 流程为：

```mermaid
sequenceDiagram
    participant CP as Control Plane
    participant Agent as Workspace Agent
    participant Provider as Git Provider
    participant Git as checkout helper

    CP->>Agent: start with source and checkout specification
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
target 必须 fail-fast，避免覆盖持久数据。只读 Git state 只在非 empty source 且
Agent ready 时可用。

## Persistent Data

control plane 将同一 Workspace 的数据映射为：

| Container path                                       | Purpose                                |
| ---------------------------------------------------- | -------------------------------------- |
| `/workspace` 或 `/workspace.enc`                     | plaintext checkout 或 ciphertext root  |
| `/upload`                                            | WebDAV 可写交换目录                    |
| `/cache`                                             | IDE 持久数据源                         |
| `/run/codespace-control`                             | provider marker 与 Agent UDS           |
| `/home/x/.{vscode-server,trae,...}/{bin,extensions}` | `/cache` 下的 IDE runtime mount        |

Agent 子进程固定以 uid/gid `5230:5230`、`HOME=/home/x` 执行。provider token
不进入镜像，deploy private key 不离开 Workspace。
