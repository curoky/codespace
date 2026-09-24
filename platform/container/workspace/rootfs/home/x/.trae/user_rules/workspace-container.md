---
description: 在 Codespace Workspace 容器内操作项目、选择工具链或诊断环境时使用
alwaysApply: true
---

<!-- markdownlint-disable MD013 -->

# Workspace Container

先读取 repository 的 `AGENTS.md`、manifest、lockfile 和 task 入口；项目约定优先。

## Runtime

- 默认用户 `x`（UID/GID 5230），`sudo` 需要 root 密码。
- 项目代码和持久数据放 `/workspace`，其他路径重建后不保留。
- 常驻服务已由系统托管，无需手动启动。
- 交互 shell 是 zsh；非登录执行器缺少环境时用 `zsh -lic '<command>'`。

## Toolchains

| Stack | Version / location |
| --- | --- |
| Python | uv-managed 3.9-3.14，默认 3.14；`uv run`，`uv python find 3.<N>` |
| Conda | `/opt/conda/condabin/conda`，默认不激活 |
| Node.js | 默认 24；26 在 `/opt/node/nodejs26/bin` |
| Go | 1.27；SDK 在 `/opt/go/go1.27.1`，tools 在 `/usr/local/profile/go/bin` |
| Rust | `/opt/rust/cargo/bin`；`CARGO_HOME=/opt/rust/cargo RUSTUP_HOME=/opt/rust/rustup` |
| Java | JDK 27 默认；JDK 8/27 在 `/opt/java/openjdk{8,27}`；`JAVA_HOME=/opt/java/openjdk27` |
| C/C++ | GCC 15；LLVM/Clang 23 在 `/opt/llvm/llvm23.1.2/bin`，Clang tools 在 `/usr/local/bin` |
| CUDA | 12.2.2，`CUDA_HOME=/usr/local/cuda`；已装 Nsight Systems/Compute |

预装工具主要在 `/usr/local/bin` 或默认 Nix profile。Protobuf 不在默认 PATH，用
`/usr/local/store/protobuf_<version>/bin`。临时工具用 `uvx` / `nix shell nixpkgs#<pkg>`。

## Services

除 SSH 外，服务只监听 loopback；外部访问需在 Project `tunnel_ports` 声明端口。

| Service | Endpoint |
| --- | --- |
| `sshd` | `0.0.0.0:22` |
| `atuin-server` | `127.0.0.1:8002` |
| `rclone-webdav` | `127.0.0.1:8004` |
| `copyparty-webdav` | `127.0.0.1:8005` |
| `ollama` | `127.0.0.1:8006` |
| `rclone-http` | `127.0.0.1:8007` |
| `miniserve-logs` | `127.0.0.1:8008` |
| `nixcache` | `127.0.0.1:8009` |
| `workspace-agent` | `/run/codespace-control/agent.sock` |

状态和日志：`s6-svstat /run/service/<service>`、`tail /var/log/s6.<service>.log`。

## Podman

内置 rootless Podman，直接 `podman`；数据在 `/opt/podman/data`，内部 container
共用 Workspace 资源边界。

## Credentials

- GitHub CLI 用前先 `gh auth status`。
- Kerberos ccache 在 `KRB5CCNAME=/opt/secret/krb5_ccache`。
- GPU 任务先 `nvidia-smi` 再 `nvcc --version`。
