---
name: use-secrets
description: 使用 csecret get KEY 读取个人凭据；用户明确要求维护 secret 时编辑并重新加密仓库中的数据。
---

# Use Secrets

- 日常只用 `csecret get KEY`，stdout 是原始 value，不追加换行。CLI 从脚本旁的
  `secrets.json.gpg` 读取，复用 `/run/secrets/codespace_workspace_key` 解密；缺失时停止
  依赖操作，不自行生成 key。不读取维护明文、不输出或复述真实凭据。

  ```bash
  token="$(csecret get github_token_all_action_rw)" && GH_TOKEN="$token" gh run view --log-failed
  auth="$(csecret get llmbox.auth.json)" && printf '%s' "$auth" > "$HOME/.codex/llmbox.auth.json"
  ```

- 仅用户明确要求维护 secret 时，在仓库的 `platform/container/workspace/tools/csecret/`
  运行 `./csecret.sh decrypt`，编辑 `secrets.json`，再运行 `./csecret.sh encrypt`。
  数据是平铺 JSON 对象，value 按字符串保存；LLMBox 凭据保存完整 JSON 字符串。
- 维护明文已 ignore，只提交 `secrets.json.gpg`，不提交 key。CLI 不自动操作 Git、更新
  安装副本或续期 token；仓库密文更新后需重建 image 或显式更新安装副本。
