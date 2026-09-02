# WSL Platform 约束

`platform/wsl/` 以
`ghcr.io/curoky/codespace:workspace-ubuntu26.04` 为 base，叠加 WSL2 专属
rootfs，并导出可由 WSL 直接导入的压平 artifact。启动与导出流程见
[`DESIGN.md`](DESIGN.md)。

## Image Contract

- WSL OCI image tag 固定为 `ghcr.io/curoky/codespace:workspace-wsl`。
- Docker build context 固定为仓库根，只复制 `platform/wsl/rootfs/`。
- WSL 继承 Workspace image 的用户 `x`（uid/gid `5230:5230`）、工具链、sshd
  与 s6 service definition；本目录不复制或修改 Workspace 私有资产。
- WSL boot 入口固定为 `/opt/codespace/wsl/boot.sh`，由
  `/etc/wsl.conf` 的 `[boot] command` 调用。
- `wsl` bundle 只选择 `atuin-login`、`atuin-daemon`、`sshd` 与
  `supercronic`；增减 service 后必须在 Dockerfile 中重编译 `/etc/s6/db`。

## Runtime Boundary

- WSL 的 PID 1 始终为 Microsoft `/init`，不使用 Workspace OCI
  `ENTRYPOINT`。`boot.sh` 手动启动 `s6-svscan`、初始化 s6-rc 并切换到 `wsl`
  bundle。
- `docker export` 会丢弃 OCI `ENV`、`ENTRYPOINT` 与 `CMD`。运行所需配置必须位于
  rootfs；shell PATH 由继承的 `/etc/zsh/zshenv` 恢复。
- `boot.sh` 写入 `SSHD_BIND=0.0.0.0`。网络暴露由 Windows mirrored networking
  或 portproxy 管理，不在 Linux rootfs 中增加第二套网络服务。
- `wsl` bundle 不包含 Workspace Agent，因此不会 bootstrap 或监听
  `agent.sock`。
- Windows keep-alive 只放在 `windows/`。默认发行版名为 `codespace`，不得把
  Scheduled Task、Windows path 或 host 配置烤入 rootfs。
- 不引入 systemd、s6-overlay 或第二套 init。

## Build And Export

```bash
platform/container/workspace/build.sh ubuntu:26.04
platform/wsl/build.sh
platform/wsl/export.sh
```

`export.sh` 默认输出 `codespace.wsl`：

```powershell
wsl --install --from-file codespace.wsl
# 或
wsl --import codespace <InstallDir> codespace.wsl
```

多架构 OCI image 只用于构建缓存与追溯；用户消费的是按 architecture 导出的
`.wsl` artifact。

## Verification

```bash
shellcheck platform/wsl/build.sh platform/wsl/export.sh
shellcheck -s sh platform/wsl/rootfs/opt/codespace/wsl/boot.sh
docker build --check -f platform/wsl/Dockerfile .
```

修改 boot、bundle、export artifact 或 Windows keep-alive 契约时同步更新
`DESIGN.md`。
