# Codex LLMBox

## Scope

原生 Codex 的 OAuth Responses 接入工具，各操作一个文件。
Taskfile 提供构建、登录与模型查询入口，Workspace 镜像提供 `codex-llmbox` 命令。
main.go 只接线 CLI；各操作的输入处理与输出位于所属文件。

## Contracts

- `login`、`models` 只读当前 Home 下的 Codex profile；直接解析固定 TOML 结构。
  目录地址和 `X-Source` 与 Codex 使用同一来源。
- 固定协议字段由代码拥有，配置值由本人维护，不做归一化或通用字段校验。运行期仅需二进制与原生 Codex。
- 凭据固定位于 `~/.codex/llmbox.auth.json`。
  原子发布且私有；只存 access_token 和 UTC expires_at。token helper 只读本地凭据，
  不联网或续期；临近过期显式 login，错误不输出凭据或原始服务响应。
- profile 模板由 rootfs 提供，仅内部标识加密，custom-job 使用
  `/run/secrets/codespace_workspace_key` 解密标识并替换模板。
  二进制只读解密后的配置，不参与加密、解密或生成配置；构建时不读取 key。
  profile 通过镜像内固定命令入口调用 `token`；登录与 Codex token helper 使用相同的 HOME。
  Codex 自己读取模型目录；独立 app-server 使用自身配置。

custom-job 完成解密后，容器内执行 `codex-llmbox login`，之后使用 `codex -p llmbox`。

## Runtime I/O

以下列出应用直接访问的路径与环境变量；`~` 表示 `os.UserHomeDir()` 返回的当前用户 Home。
二进制不修改环境变量，不读取 stdin。

三个业务命令仅通过 home API 读取 `HOME`（Linux/macOS），为空时报错。
不读取业务环境变量、secrets、`.env`、`CODEX_HOME` 或 `XDG_*`，不支持外部指定目录。

### Local Paths

| 路径 | 访问者与行为 |
| --- | --- |
| `~/.codex/` | `login` 创建目录并设置为 `0700` |
| `~/.codex/llmbox.config.toml` | `login`、`models` 只读 `_llmbox.issuer`、`_llmbox.client_id`，以及 `model_providers.llmbox` 的 `model_catalog_url`、`http_headers.X-Source`；Codex 使用同一 profile |
| `~/.codex/llmbox.auth.json` | `login` 原子替换为 `0600`；`token`、`models` 只读 |
| `~/.codex/.llmbox.auth.json*` | `login` 在同目录创建 `0600` 临时文件，发布时 rename，正常返回时清理 |

镜像构建期安装二进制到
`/home/x/.local/opt/stage_codex_llmbox/bin/codex-llmbox`，
并创建 `/home/x/.local/bin/codex-llmbox` 链接；这些不是运行期写入。
二进制不访问 Codex 的主 `config.toml`、凭据或模型缓存，不保存模型目录。
`token` 不读取 profile。`_llmbox` 是本工具的扩展 key，Codex 默认忽略；
不要使用 `--strict-config`，它会拒绝这个扩展 key。
`X-Source` 须是网关已登记的 tenant；未登记值可导致空目录及推理 HTTP 401 `tenant not found`。

### Network and Output

| 命令 | 网络 | 输出 |
| --- | --- | --- |
| `login` | POST issuer + `/oauth2/device/code`，轮询 POST issuer + `/oauth2/access_token` | stderr：浏览器授权地址、user code、凭据保存位置 |
| `token` | 无 | stdout：带 `at-` 前缀的 token，供 Codex 作为 Bearer 值使用 |
| `models` | GET profile 的 `model_catalog_url` | stdout：文本表格或 `--json` JSON |

命令错误写入 stderr，help 写入 stdout。二进制不启动 Codex 或浏览器；profile 中的
模型目录与 Responses 地址供 Codex 后续使用，推理请求由 Codex 发起。

## Validation

运行仓库根目录的 `task check:full`；HTTP/TLS fixture 验证协议与文件合同，不代表真实服务授权或模型权限。
镜像改动另按 Workspace 文档构建并验证 custom-job 模板替换、失败保留、原生 Codex profile 与 token helper。
