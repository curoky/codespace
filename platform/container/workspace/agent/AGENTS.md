# Workspace Agent

仅通过 Unix socket 向控制面提供最小 bootstrap 与 Git 状态协议。只消费控制面注入的输入，
不读取项目配置、不接收 provider token，也不管理 Podman 或 Host。

## Contracts

- provider 授权由控制面完成，private deploy key 留在 Workspace，协议只暴露 public key。
- bootstrap 失败必须能通过存活的 server 查询；错误详情有界且不得泄露 secret。
- Git 状态汇总所有 checkout 的未提交修改及未被 remote 包含的提交；包含 detached HEAD，
  排除 Agent checkpoint refs，避免漏报用户工作或产生误报。
- 外部命令使用 argv，不拼接 shell。
- 协议变化同步控制面 client `src/codespace/workspaces/agent.py` 与双方 lifecycle tests。

依赖由本目录独立的 `pyproject.toml` 与 `uv.lock` 管理。通用检查由根 `Taskfile.yaml`
统一执行；Agent 变更还需按上层约定构建主 image。
