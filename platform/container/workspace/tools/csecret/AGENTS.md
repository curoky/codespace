# Csecret

## Scope

个人 Bash secret CLI，用现有 GPG/jq，不增加服务。数据固定在 [csecret.sh](csecret.sh)
旁的 `secrets.json.gpg`，复用 `/run/secrets/codespace_workspace_key` 做 AES256 对称加密。

## Contracts

- 日常只用 `csecret get KEY`：内存管道解密，输出原始 value，不追加换行，不生成明文文件。
  JSON 是平铺 key/value 对象；token、多行文本、LLMBox 完整凭据 JSON 都保存为字符串。
- 维护时在本目录运行 `./csecret.sh decrypt`，编辑 `secrets.json`，再运行
  `./csecret.sh encrypt`。加密前检查 JSON 对象，失败保留旧密文；两个命令原子替换目标文件，
  不自动删除维护明文。
- 只提交 `secrets.json.gpg`；明文、编辑器及 CLI 临时文件由 Git/Docker ignore 排除，
  image 只复制脚本和密文。
  key 不提交；CLI 不自动操作 Git、不同步应用凭据、不负责 OAuth 续期。
- image 内脚本和密文装到 `~/.local/opt/csecret/`；CLI 通过真实脚本路径定位数据，
  不依赖当前目录，不使用维护明文作日常数据源。密文更新后需重建 image 或显式更新安装副本。
- `custom-job` 读取 `traecli_download_curl`（URL 值）和 LLMBox 模板标识；GitHub/Atuin
  启动登录也通过 `get` 读取凭据，不再依赖对应 Podman secret 挂载。

## Validation

`task csecret:test` 使用真实 GPG/jq 和临时口令；image 验证遵循 Workspace 文档。
