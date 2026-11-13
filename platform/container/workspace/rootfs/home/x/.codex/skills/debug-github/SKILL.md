---
name: debug-github
description: 排查 GitHub 认证、Actions 日志或需要额外权限的 GitHub API。
---

# Debug GitHub

- 只读查询直接使用 `gh`，默认认证来自 `/run/secrets/github_token_public_read`。
- 查询 GitHub Actions 或其他需要额外权限的 API 时，只为当前命令设置 token：

  ```bash
  GH_TOKEN="$(cat /run/secrets/github_token_all_action_rw)" gh run view --log-failed
  ```

- token 仅作用于当前命令，不要全局 export 或输出其内容。
