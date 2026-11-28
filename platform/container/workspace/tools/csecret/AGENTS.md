# Csecret

## Scope

个人 Bash secret CLI；入口见 [csecret.sh](csecret.sh)，使用与维护见
[use-secrets](../../rootfs/home/x/.codex/skills/use-secrets/SKILL.md)。

## Contracts

- 数据为平铺字符串对象；`get KEY` 从脚本旁的密文读取原始 value，不追加换行或落地明文。
- Linux key 来自 `/run/secrets/codespace_workspace_key`；macOS 用 yq 读取
  `~/.config/codespace/config.yaml` 的 `secrets.codespace_workspace_key` 并校验非空字符串。
  key 只经内存与 stdin 传给 GPG；缺失或无效直接失败。
- macOS 直接使用仓库脚本和密文；Linux image 使用独立副本，更新后须显式分发。
- 加解密 staging 成功后才替换目标，失败保留原文件并清理临时文件。
- 明文和 key 不进入 Git/image；凭据发布、认证与续期由消费者拥有。

## Validation

`task csecret:test` 使用真实 GPG/jq/yq；image 验证遵循 Workspace 文档。
