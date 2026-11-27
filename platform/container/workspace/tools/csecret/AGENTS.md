# Csecret

## Scope

个人 Bash secret CLI，复用 Workspace key 与现有 GPG/jq，不增加服务。入口见
[csecret.sh](csecret.sh)，日常使用和维护流程见
[use-secrets](../../rootfs/home/x/.codex/skills/use-secrets/SKILL.md)。

## Contracts

- 日常只用 `csecret get KEY`：内存管道解密，输出原始 value，不追加换行，不生成明文文件。
  数据为平铺字符串对象，维护明文不作运行时数据源。
- 通过真实脚本路径定位密文，不依赖当前目录；仓库更新不会改变已安装副本，需显式分发。
- 明文和 key 不进入 Git/image；CLI 不操作 Git、同步应用凭据或续期 OAuth，消费者拥有
  凭据发布和认证行为。

## Validation

`task csecret:test` 使用真实 GPG/jq 和临时口令；image 验证遵循 Workspace 文档。
