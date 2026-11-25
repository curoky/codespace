# Codex LLMBox

## Scope

原生 Codex 的 OAuth Responses 接入工具，拥有登录、本地 token helper 与模型目录查询。
[main.go](main.go) 只接线 CLI，各操作一个文件；[Taskfile.yaml](Taskfile.yaml) 提供构建
与操作入口。运行期只需二进制与原生 Codex，不参与 profile 加密、解密或生成。

## Contracts

- `login`、`models` 直接解析当前 Home 下的固定 TOML profile，目录地址和 `X-Source` 与
  Codex 使用同一来源；协议字段由代码拥有，配置值由本人维护，不增加归一化或通用校验层。
- 凭据只存 access_token 与 UTC expires_at，原子发布且私有；token helper 只读本地凭据，
  不联网或续期。临近过期显式 login，错误不输出凭据或原始服务响应。
- rootfs/custom-job 拥有模板与内部标识解密，使用 `/run/secrets/codespace_workspace_key`；
  二进制只读已解密 profile，构建时不读取 key。profile 经固定入口调用 `token`，
  login 与 token helper 使用相同 HOME；独立 app-server 使用自身配置。

## Main Flows

custom-job 发布 profile 后，由用户显式执行 `codex-llmbox login`；工具向 issuer 发起 device
授权并提示用户完成浏览器操作，轮询成功后发布凭据。随后 `codex -p llmbox` 调用本地
`token` 获取 Bearer 值；模型目录与 Responses 推理由 Codex 自己读取或请求。

## Runtime I/O

- **Reads**：以 `os.UserHomeDir()` 确定 `~/.codex/`，不接受外部目录，不用 `CODEX_HOME`
  或 `XDG_*` 改写来源，也不读 stdin、secret 或 `.env`。`login`、`models` 读取
  `llmbox.config.toml`，`token`、`models` 读取 `llmbox.auth.json`；`token` 不读 profile。
  字段定义见 [connection.go](connection.go)，不访问 Codex 主配置、主凭据或模型缓存。
- **Writes**：[OAuth](oauth-device-auth.go) 将 `.codex` 目录设为 `0700`，用同目录私有
  临时文件原子替换 `0600` 凭据并清理临时文件。只改变该用户目录权限，不修改系统配置；
  二进制的 image 安装路径属于构建期，不是工具运行期写入。
- **Network**：`login` 向 profile issuer 的 device-code/token endpoint 提交 client、scope
  和 device 授权信息；`models` 向 `model_catalog_url` 发送 Bearer token 与 `X-Source`。
  endpoint 见 [OAuth](oauth-device-auth.go) 和 [model catalog](model-catalog.go)，不保存目录，
  `token` 完全离线。工具不启动浏览器或 Codex，不代发推理请求。
- **Results & Failure**：login 提示和错误写 stderr；token 输出带 `at-` 前缀的凭据到 stdout，
  models 输出表格或 JSON，help 写 stdout。授权或凭据发布失败不替换已有凭据；输出失败
  不代表凭据一定未发布，不提供自动续期或回滚。

## Pitfalls

- `_llmbox` 是工具扩展 key，Codex 默认忽略；不要用 `--strict-config`，它会拒绝该 key。
- `X-Source` 必须是网关登记的 tenant；未登记时可出现空目录或推理 401 `tenant not found`，
  须核对 profile 与网关登记，不能把成功登录当作模型访问授权。

## Validation

HTTP/TLS fixture 验证协议、输出与文件合同，不代表真实服务授权或模型权限。完整验证
入口遵循根文档；image 变化另验证 custom-job 替换、失败保留、原生 profile 与 token helper。
