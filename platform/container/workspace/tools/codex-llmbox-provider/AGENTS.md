# Codex LLMBox Provider

## Scope

原生 Codex 的 OAuth Responses 接入工具；独立 Go module，src 平铺，各操作一个文件。
Taskfile 是开发入口，Workspace 镜像提供 `codex-llmbox-provider` 命令。
main.go 只接线 CLI；各操作的输入处理与输出位于所属文件。

## Contracts

- 默认从固定 `/run/secrets` 读取接入参数；`--env` 显式改为环境变量，字段映射由 connection.go
  拥有。输入移除首尾空白，缺失报错，不跨来源补齐；secret 文件须对运行用户可读。
  容器通过 secret 提供接入参数。
- 固定协议字段由代码拥有，输入由本人维护。运行期仅需二进制与原生 Codex。
- 凭据固定位于 `~/.codex/llmbox.auth.json`。
  原子发布且私有；只存 access_token 和 UTC expires_at。token helper 只读本地凭据，
  不联网或续期；临近过期显式 login，错误不输出凭据或原始服务响应。
- profile 固定写入 `~/.codex/llmbox.config.toml`，记录当前二进制绝对路径，以 `token` 参数调用。
  登录与 Codex token helper 必须使用相同的 HOME；移动二进制后需核对 profile。
  `configure --write` 拒绝覆盖不同内容。
  Codex 自己读取模型目录；独立 app-server 使用自身配置。

容器内先执行 `codex-llmbox-provider login`、`codex-llmbox-provider configure --write`，
之后使用 `codex -p llmbox`。日常 Codex 启动与 token helper 无需读取 secret 文件。

## Runtime I/O

以下列出应用直接访问的路径与环境变量；`~` 表示 `os.UserHomeDir()` 返回的当前用户 Home。
二进制不修改环境变量，不读取 stdin。

### Connection Inputs

`login`、`configure`、`models` 均要求四项完整输入。默认只读下表 secret 文件；
`--env` 时只读对应环境变量。`token` 不读取这些输入，传入 `--env` 也不改变其行为。

| 默认只读文件 | `--env` 只读变量 | 用途 |
| --- | --- | --- |
| `/run/secrets/codespace_llmbox_oauth_issuer` | `OAUTH_ISSUER` | OAuth issuer 基础地址 |
| `/run/secrets/codespace_llmbox_oauth_client_id` | `OAUTH_CLIENT_ID` | Device Flow 的 client ID |
| `/run/secrets/codespace_llmbox_base_url` | `LLMBOX_BASE_URL` | 网关基础地址 |
| `/run/secrets/codespace_llmbox_source` | `LLMBOX_SOURCE` | `X-Source` header 值 |

四个业务命令还通过 home API 读取 `HOME`（Linux/macOS），为空时报错。
不读取 `.env`、`CODEX_HOME` 或 `XDG_*`，不支持外部指定凭据目录。

### Local Paths

| 路径 | 访问者与行为 |
| --- | --- |
| `~/.codex/` | `login` 创建目录并设置为 `0700`；`configure --write` 创建缺失的父目录，新目录权限为 `0700` |
| `~/.codex/llmbox.auth.json` | `login` 原子替换为 `0600`；`token`、`models` 只读；`configure` 不读取 |
| `~/.codex/.llmbox.auth.json*` | `login` 在同目录创建 `0600` 临时文件，发布时 rename，正常返回时清理 |
| `~/.codex/llmbox.config.toml` | `configure --write` 新建 `0600` 文件；存在则只读比较，相同内容幂等，不同内容报错；不带 `--write` 时不访问文件 |
| 当前 executable | `configure` 通过 `os.Executable()` 获取路径；Linux 读取 `/proc/self/exe` 链接，不安装或更新二进制 |

镜像构建期安装二进制到
`/home/x/.local/opt/stage_codex_llmbox_provider/bin/codex-llmbox-provider`，
并创建 `/home/x/.local/bin/codex-llmbox-provider` 链接；这些不是运行期写入。
二进制不访问 Codex 的主 `config.toml`、凭据或模型缓存，不保存模型目录。

### Network and Output

| 命令 | 网络 | 输出 |
| --- | --- | --- |
| `login` | POST issuer + `/oauth2/device/code`，轮询 POST issuer + `/oauth2/access_token` | stderr：浏览器授权地址、user code、凭据保存位置 |
| `token` | 无 | stdout：带 `at-` 前缀的 token，供 Codex 作为 Bearer 值使用 |
| `configure` | 无 | stdout：TOML；`--write` 时改为写文件并在 stderr 提示 |
| `models` | GET 网关基础地址 + `models` | stdout：文本表格或 `--json` JSON |

命令错误写入 stderr，help 写入 stdout。二进制不启动 Codex 或浏览器；profile 中的
模型目录与 Responses 地址供 Codex 后续使用，推理请求由 Codex 发起。

## Validation

运行 `task check:full`；HTTP/TLS fixture 验证协议与文件合同，不代表真实服务授权或模型权限。
镜像改动另按 Workspace 文档构建并验证 secret 读取、profile 与 token helper。
