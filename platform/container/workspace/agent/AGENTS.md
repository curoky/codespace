# Workspace Agent

## Scope

通过 Unix socket 向控制面提供最小 bootstrap 与 Git 状态协议。只消费控制面注入的输入，
不读取项目配置、不接收 provider token，不管理 Podman 或 Host。独立 Go executable 使用
标准库 HTTP server，不依赖 Python runtime。

## Contracts

- provider 授权由控制面完成，private deploy key 留在 Workspace，协议只暴露 public key。
  bootstrap 失败后 server 仍可查询，错误详情有界且不得泄露 secret。
- bootstrap 与 server 同进程运行，状态经锁保护；授权等待与外部命令响应 shutdown
  cancellation。外部命令用 argv，不拼接 Shell。
- 只监听 bind-mounted Unix socket；保留 Host-side OpenSSH 读写权限，访问范围由受限父
  目录控制，不依赖 container UID 与 Host 登录 UID 相同。
- [git.go](git.go) 汇总全部 checkout 的未提交修改与未被 remote 包含的提交，包含 detached
  HEAD，排除 Agent checkpoint refs；不能漏报用户工作或将 checkpoint 当作未推送工作。
- 协议变化同步控制面 [client](../../../../src/codespace/workspaces/agent.py) 与双方 lifecycle tests。
  默认 filesystem 合同由 [main.go](main.go) 拥有；socket/checkout 覆盖只用于隔离测试，
  不由控制面传递。

## Main Flows

[agent.go](agent.go) 读取注入的 source/open path，检查 provider source 的 Git 可访问性；
需要授权时进入 awaiting-provider，控制面注册 public key 后放行。按 source 调用 checkout
helper，准备 open path 后进入 ready；失败进入 failed，server 保留状态供控制面读取。
Git-state 仅在 ready 后检查 repository，不负责清理、迁移或恢复数据。

## Validation

[agent_test.go](agent_test.go) 覆盖 Agent 行为；控制面测试使用真实 executable 与 Unix
socket 验证双方协议。Agent 变化还需按 Workspace 约定构建主 image。
