---
description: 在 Codespace Workspace 容器内操作项目、选择工具链或诊断环境时使用
alwaysApply: true
---

<!-- markdownlint-disable MD013 -->

# Workspace Container

## 开始工作

- 只把项目修改和需要保留的产物写入 `/workspace`；容器重建后其他路径不保留。
- 默认以用户 `x` 执行，不假设 `sudo` 可用。

## Toolchains

- Python 项目统一使用 `uv` 管理依赖和运行命令。Python 3.9-3.14 安装在
  `/opt/uv/python`，使用 `uv python find 3.<N>` 选择版本。
- Conda 安装在 `/opt/conda`，但默认不要使用；仅在项目明确要求 Conda 时启用。
- C/C++ 默认使用 Nix default profile
  `/nix/var/nix/profiles/default/bin` 中的 GCC 15；另有 Clang 23，位于
  `/opt/llvm/llvm23.1.2/bin`。
- Java 默认使用 `/opt/java/openjdk27` 中的 JDK 27；另有 JDK 8，位于
  `/opt/java/openjdk8`。切换版本时同时设置 `JAVA_HOME` 和 `PATH`。
- Node.js 默认使用 `/opt/node/nodejs24` 中的 Node.js 24；另有 Node.js 26，
  位于 `/opt/node/nodejs26`。切换版本时将对应 `bin` 目录放到 `PATH` 前部。
- Go 1.27.1 位于 `/opt/go/go1.27.1`，Go 工具位于 `/usr/local/profile/go/bin`。
- Rust stable 位于 `/opt/rust`，Cargo 可执行文件位于 `/opt/rust/cargo/bin`。
- CUDA 12.2.2 位于 `/usr/local/cuda-12.2`，默认链接为 `/usr/local/cuda`。
- 一次性 Python 工具使用 `uv tool` 管理；其他一次性工具使用
  `nix-env -iA nixpkgs.<package>` 安装。

## Resource Volume

- 大型工具位于只读挂载的 `codespace-resource` volume，挂载点为 `/opt/resource`。
- `/opt/go`、`/opt/rust`、`/opt/llvm`、`/opt/java`、`/opt/node`、`/opt/nvidia`
  和 `/usr/local/cuda-12.2` 等常用路径是指向该 volume 的链接。
- 不要修改 `/opt/resource`，也不要用本地目录替换这些链接。

## 托管服务

- 该镜像使用 s6 管理服务，不支持 systemd；不要调用 `systemctl`。
- 用 `s6-svstat /run/service/<service>` 查看状态，用
  `tail /var/log/s6.<service>.log` 查看日志。

## Podman

- 容器内已配置 rootless Podman，直接使用 `podman build` 和 `podman run`。
- Podman 固定连接 `unix:///run/user/5230/podman/podman.sock`，不要改连 Host Podman。
- Host 通常使用 cgroup v1，因此内部 Podman 固定使用 `cgroups = "disabled"`；
  不要启用 cgroups，也不要依赖内部 container 的 cgroup 资源限制。
- Podman 数据保存在 `/opt/podman/data`。

## GitHub

- `gh` 已通过 token 登录，可直接用于查询 repository、workflow 和 run。
- 排查 GitHub Actions 时优先使用 `gh run list`、`gh run view` 和
  `gh run view --log-failed` 获取失败日志。
