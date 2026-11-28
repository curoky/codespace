---
name: use-secrets
description: 使用 csecret get KEY 读取个人凭据；用户明确要求维护 secret 时编辑并重新加密仓库中的数据。
---

# Use Secrets

- 日常用 `csecret get KEY`，输出原始 value，不追加换行；不读取维护明文或展示真实凭据。
  Linux key 来自 `/run/secrets/codespace_workspace_key`；macOS 来自
  `~/.config/codespace/config.yaml` 的 `secrets.codespace_workspace_key`，缺失时停止。
- 仅用户明确要求维护时，在仓库的 `platform/container/workspace/tools/csecret/`
  执行 `./csecret.sh decrypt`，编辑 `secrets.json`，再执行 `./csecret.sh encrypt`。
  数据为平铺字符串对象；只提交密文，不提交明文或 key。
- macOS 用 `~/workspace/codespace/platform/container/workspace/tools/csecret/csecret.sh get KEY`；
  Linux 密文更新后须重建 image 或同步副本，Codespace token 更新后须重启控制面。
- LLMBox 从 `~/.codex/llmbox.auth.json` 提取 `llmbox_access_token` 和
  `llmbox_expires_at`（UTC RFC3339），一起更新，不存完整 JSON，不把凭据放进命令参数。
  `custom-job` 每次启动从安装密文组装 auth；重新 login 后须回存并同步，否则重启恢复旧凭据。
