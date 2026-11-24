# Workspace Agent

## Scope

仅通过 Unix socket 向控制面提供最小 bootstrap 与 Git 状态协议。只消费控制面注入的输入，
不读取项目配置、不接收 provider token，也不管理 Podman 或 Host。

## Contracts

- provider 授权由控制面完成，private deploy key 留在 Workspace，协议只暴露 public key。
- bootstrap 失败必须能通过存活的 server 查询；错误详情有界且不得泄露 secret。
- Git 状态汇总所有 checkout 的未提交修改及未被 remote 包含的提交；包含 detached HEAD，
  排除 Agent checkpoint refs，避免漏报用户工作或产生误报。
- 外部命令使用 argv，不拼接 shell。
- bootstrap 与 server 同进程运行，状态通过锁保护；授权等待与外部命令响应 shutdown
  cancellation。只监听 Unix socket，不提供 TCP listener。
- Unix socket 保留 Host-side OpenSSH 的读写权限，访问范围由受限的父目录控制，不能依赖
  container 用户 UID 与 Host 登录用户 UID 相同。
- 协议变化同步控制面 client `src/codespace/workspaces/agent.py` 与双方 lifecycle tests。

Agent 是独立 Go executable，与两个 installer 共用上层 Go module。HTTP server 使用标准库，
不依赖 Python runtime。默认 filesystem 合同写在入口中；socket 与 checkout helper 的可选
覆盖用于隔离测试，不由控制面传递。

## Validation

Go tests 覆盖 Agent 行为，控制面 tests 通过真实
executable 与 Unix socket 验证双方协议。Agent 变更还需按上层约定构建主 image。
