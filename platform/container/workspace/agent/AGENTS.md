# Workspace Agent

此目录是独立的 Python 3.14 application，运行在每个 Workspace 内，通过 bind-mounted Unix
socket 向 macOS 控制面暴露最小 bootstrap/Git protocol。它不接收 provider token，也不管理
Podman 或 Host。

## Protocol And State

- `GET /status` 返回 `bootstrapping`、`awaiting-provider`、`ready` 或 `failed`；provider source
  在 public deploy key 就绪后停在 `awaiting-provider`。
- `POST /provider-ready` 只解除 provider checkout gate。private key 始终留在 Workspace，
  response 只包含 public key。
- `GET /git-state` 只在非-empty、ready Workspace 上可用，报告 uncommitted 与未被 remote
  包含的 commit；agent checkpoint refs 不应造成 false positive。
- server 只绑定 `/run/codespace-control/agent.sock`，不开放 TCP。启动前清理旧 socket，退出时
  再清理。
- bootstrap 在后台线程执行，所有失败转换为 bounded `failed` detail，供控制面轮询；不要让
  checkout failure 终止 UDS server 后丢失诊断。

## Inputs And Checkout

- `CODESPACE_SOURCE_TYPE`、`CODESPACE_CHECKOUT_PATH`、`CODESPACE_OPEN_PATH` 以及非-empty source
  的 clone URL/Git args 由控制面注入。Agent 不读取项目配置文件。
- empty source 只创建 open path；generic Git source 直接 checkout；GitHub/GitLab source 先生成
  deploy key、等待授权，再 clone。
- command 以 argv 执行，不通过 shell 拼接。错误摘要可以包含命令结果，但不得读取或输出
  secret/token。
- protocol model 或 endpoint 变化必须同步 `src/codespace/workspaces/agent.py` client 和双方
  lifecycle tests；不保留旧 endpoint fallback。

## Dependencies And Validation

`pyproject.toml` 与 `uv.lock` 只属于内嵌 Agent；依赖变化使用该 project 更新 lock。验证：

```bash
uv run pytest tests/workspaces/test_agent.py
MYPYPATH=platform/container/workspace/agent uv run mypy \
  platform/container/workspace/agent/agent.py
uv lock --project platform/container/workspace/agent --check
platform/container/workspace/build.sh
```

最终仍运行 `task check:full`。
