---
name: debug-github
description: >-
  调试 GitHub 访问、gh 认证、GitHub Actions、workflow run 和 check failure；当任务需要查看
  Actions 日志或使用非公开只读 GitHub API 时调用。
---

# Debug GitHub

- 公开仓库的只读操作直接使用 `gh`；默认认证来自
  `/run/secrets/github_token_public_read`。
- 查询 GitHub Actions 或其他需要额外权限的 API 时，只为当前命令设置 token：

  ```bash
  GH_TOKEN="$(cat /run/secrets/github_token_all_action_rw)" gh run view --log-failed
  ```

- 根据调试目标替换 `gh` 子命令，不要全局 `export GH_TOKEN`，不要输出 token 内容。
