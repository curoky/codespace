# Codex LLMBox

## Scope

为原生 Codex 提供 OAuth 登录、本地 token helper 与模型目录查询；不生成或解密 profile，
不启动 Codex/浏览器，也不代发推理。CLI 入口见 [main.go](main.go)，操作入口见
[Taskfile.yaml](Taskfile.yaml)；profile/auth 初始化由 [Workspace](../../AGENTS.md) 拥有。

## Contracts

- 工具与 Codex 读取同一 profile，issuer/catalog/`X-Source` 由配置拥有，字段以
  [connection.go](connection.go) 为准，不增加归一化或通用校验层。
- token helper 完全离线，不续期；临近过期显式 login，login/helper 使用同一 HOME。
  独立 app-server 使用自身配置；成功登录不代表模型访问权限。

## Runtime I/O

- **Reads**：只读用户 home 下的 LLMBox profile/auth，不用 `CODEX_HOME`/`XDG_*`
  覆盖目录，不读 stdin、secret/.env 或 Codex 主配置/凭据/cache；token 不读 profile。
- **Writes**：[OAuth](oauth-device-auth.go) 原子发布本地私有凭据，不改系统配置或 secret store。
- **Network**：login 访问 issuer OAuth endpoint；[models](model-catalog.go) 访问 catalog，
  携带 Bearer token/`X-Source`，不保存目录。
- **Results & Failure**：login 提示/错误到 stderr，token 凭据到 stdout；错误不泄露凭据或
  原始响应。授权或发布失败保留旧凭据，发布后的输出失败不回滚。

## Pitfalls

`_llmbox` 扩展 key 不支持 Codex `--strict-config`；`X-Source` 须为登记 tenant，空目录或
401 `tenant not found` 应核对 profile/网关登记，不能用重新登录代替权限核对。

## Validation

HTTP/TLS fixture 检查协议/文件/输出，不证明真实授权或模型权限。image 行为变化另验证
custom-job 替换与失败保留、原生 profile/token helper；通用检查遵循根文档。
