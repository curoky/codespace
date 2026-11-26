---
name: debug-github
description: 排查 GitHub 认证、Actions 日志或需要额外权限的 GitHub API。
---

# Debug GitHub

- 只读查询直接使用 `gh`，默认认证由启动任务从 `csecret get github_token_public_read` 获取。
- 按操作选择 csecret key：
  `github_token_public_read` 用于公开仓库只读查询；`github_token_all_read` 用于私有仓库
  只读查询；`github_token_all_action_rw` 用于 Actions 调试及需要 Actions 写权限的操作。
- 使用 `csecret get KEY` 获取 token，只为目标命令设置 `GH_TOKEN`；用 `&&` 确保读取失败
  时不执行后续 API 请求。私有仓库与 Actions 的示例：

  ```bash
  token="$(csecret get github_token_all_read)" && GH_TOKEN="$token" gh repo view OWNER/REPO
  ```

  ```bash
  token="$(csecret get github_token_all_action_rw)" && GH_TOKEN="$token" gh run view --log-failed
  ```

- `csecret get` 从安装的密文读取，输出原值且不追加换行；不要从 `/run/secrets/github_*`
  或维护明文取 token，不要为调试运行整文件 `decrypt`。
- token 仅作用于当前命令，不要全局 export、输出其内容或使用 `set -x`。读取失败先报告缺失
  key/密文/Workspace key，不自行生成或替换凭据；拥有写权限不代表用户授权执行写操作。
