# Workspace Agent

## Scope

通过 Unix socket 提供 bootstrap/Git 状态协议；只消费控制面注入的输入，不读项目配置、
接收 provider token 或管理 Podman/Host。[agent.go](agent.go) 检查 source 可访问性，
必要时等待控制面授权，再调用 checkout helper 并准备 open path；ready 后允许 Git-state。

## Contracts

- private deploy key 留在 Workspace，协议只暴露 public key；bootstrap failed 时 server
  仍可查询，错误有界且不泄露 secret。
- bootstrap/server 同进程，状态经锁保护，授权等待/外部命令响应 shutdown cancellation；
  外部命令用 argv，不拼 Shell。运行期不依赖 Python，不负责数据清理/迁移/恢复。
- 只监听 bind-mounted Unix socket；Host-side OpenSSH 权限由受限父目录保障，不依赖
  container/Host UID 相同。默认路径与测试覆盖参数以 [main.go](main.go) 为准。
- [git.go](git.go) 汇总全部 checkout 的未提交/未被 remote 包含的工作，含 detached HEAD，
  排除 Agent checkpoint refs，不能漏报或将 checkpoint 误报为用户提交。

## Validation

[agent_test.go](agent_test.go) 检查行为；协议变化同步控制面
[client](../../../../src/codespace/workspaces/agent.py) 与双方真实 executable/Unix socket
测试，artifact 行为变化按 Workspace 约定验证主 image。
