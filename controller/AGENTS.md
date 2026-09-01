# Codespace 控制面约束

`controller/` 是仅监听本机的单进程控制面。它读取静态配置，通过 system OpenSSH 连接远端
rootful Podman，或直连本地 rootful Podman Machine，并提供原生 Web UI。

本文只记录实现约束和工作入口。架构、数据布局、生命周期、接口关系和后续瘦身边界见
[`DESIGN.md`](DESIGN.md)。仓库级约束见 [`../AGENTS.md`](../AGENTS.md)，开发镜像契约见
[`../images/dev/AGENTS.md`](../images/dev/AGENTS.md)。

## 模块边界

| 路径 | 职责 |
| --- | --- |
| `app.py`、`api.py`、`__main__.py` | FastAPI 装配、HTTP 路由和进程入口 |
| `config.py`、`models.py` | 配置 schema、运行规格、资源标识和 API model |
| `service.py` | environment/deployment application service 与 operation 调度 |
| `dashboard.py`、`operations.py` | Dashboard 只读投影和进程内 operation store |
| `inventory.py`、`container.py`、`agent.py` | Podman inventory、容器参数翻译、workspace agent contract 与 UDS client |
| `deployment.py` | host 级 deployment 的 reconcile、clean、purge 和状态投影 |
| `provider.py`、`ssh.py` | Git provider deploy key 与 SSH 投影 |
| `runtime/` | 无 Codespace 业务知识的 Podman、SSH、文件和 Compose 原语 |
| `tools/` | 不依赖 Web 进程的 dry-run-first 运维命令 |
| `assets/ssh/`、`static/`、`tests/` | 固定 SSH 资产、原生 Web UI 和测试 |

依赖只能由业务层指向 `runtime/`。`runtime/` 不得 import 控制面业务模块。配置解析、inventory
校验、容器参数翻译和生命周期编排保持分离；Web 路由只做输入转换和错误映射。

## 运行与验证

配置入口固定为 `~/devspace/config.extend.yaml`，可用 `extends: config.yaml` 叠加仓库内共享配置。
映射递归合并，入口层优先；标量和列表整体替换。配置只在启动时读取。

```bash
uv sync
uv run python -m controller
controller/run.sh

uv run python -m controller.tools.cleanup_deploy_keys
uv run python -m controller.tools.cleanup_workspaces
uv run python -m controller.tools.sync_secrets

task check
```

`task check` 还会检查 `images/dev` 的 workspace helper，需要 Bash 5、`shfmt`、ShellCheck 和 Bats。
维护命令默认只输出计划；显式传入 `--no-dry-run` 才允许修改 host 或 provider 状态。

## 配置约束

- 顶层结构为 `workspaces`、`hosts`、可选 `deployments`、`tokens` 和 `secrets`；未知字段直接拒绝。
- `workspaces.defaults` 提供开发容器的 `image` 与 `container`，`workspaces.items` 声明
  `repo`、`git` 或 `blank` workspace。
- workspace 的 container 解析顺序为 `defaults -> host -> workspace`；每层按字段整体覆盖。
- deployment 是无 workspace、SSH 投影和 repository credential 的自包含镜像；解析顺序为
  `host -> deployment`，不继承开发容器默认值。部署位置由 `hosts.<host>.deployments` 声明。
- `container` 只接受 `controller/runtime/compose/` 定义的 Compose 子集。最终
  `network_mode` 必须是 `host` 或 `bridge`。
- `published_ports` 使用 `remote` 或 `local:remote`；workspace 仅允许在 bridge network 发布端口。
- `sidecar` deployment 通过 `container.environment.ATUIN_PORT` 配置 Atuin 端口（默认 `8002`）；bridge
  network 下 `published_ports` 的容器端口必须与其一致。
- `llm-vllm` 与 `llm-sglang` deployment 使用 host network，不声明 `published_ports`，并通过
  `LLM_HOST=127.0.0.1` 将 API 限制在宿主 loopback。
- 用户 volume 不得与 `/workspace`、`/workspace.enc`、`/upload`、`/cache`、
  `/run/codespace-control` 相同或形成父子覆盖。
- secret 必须预先注册到目标 Podman host。控制面只引用 secret 名，不读取明文；顶层
  `secrets` 只供带外同步命令使用。
- workspace、instance、deployment ID 匹配 `^[a-z0-9][a-z0-9-]{0,31}$`；host alias 匹配
  `^[a-z0-9][a-z0-9.-]{0,62}$`。
- `config.yaml` 是可提交的共享 base；token、secret、host 和私有 workspace 放在被 Git 忽略的
  `config.extend.yaml`。

具体字段及交叉校验以 `controller/config.py` 的 Pydantic model 和仓库根
[`config.yaml`](../config.yaml) 为准，不在本文复制完整 schema。

## 资源与 Host 契约

- 开发用户固定为 `x`，uid/gid `5230:5230`。
- Environment identity 为 `codespace-<host>-<workspace>-<instance>`，带
  `codespace.managed=true` 和完整身份 label。
- Deployment identity 为 `codespace-<deployment>`，只带 `codespace.deployment*` label；
  两类 inventory 的 label filter 必须互斥。
- Environment 的 SSH 端口从 identity 确定性映射到 `20000-29999`；冲突直接拒绝。
- Host 持久数据只使用 `~/codespace`：environment 位于
  `workspaces/<workspace>/<instance>/{workspace,upload,cache,control}`，deployment 位于
  `deployments/<deployment>`。准确 mount 关系见 [`DESIGN.md`](DESIGN.md#host-数据布局)。
- SSH host 必须提供 rootful Podman Unix socket、可写 login home、GNU `env` 和 `find`，并允许 OpenSSH
  StreamLocal forwarding。
- Podman Machine 必须已启动且启用 rootful mode。跨架构镜像依赖 host 预先配置 `binfmt_misc`。
- SSH host 的 Podman socket和逐实例 agent socket通过进程私有 Unix socket转发；连接复用、调用有界超时，
  进程退出时关闭。

## 生命周期约束

- Podman inventory 是运行状态的唯一事实来源。缺失、非法或与配置不一致的 label 都是显式错误，
  不推断默认值。
- Environment 创建必须按 `DESIGN.md` 的顺序执行：校验、读取 host 环境、拉镜像、建目录、清理旧 control
  marker、以 `CODESPACE_WORKSPACE_*` 环境变量建容器、建立 UDS tunnel、完成 provider握手和 bootstrap、
  SSH probe、刷新 SSH投影。
- `repo` workspace 的镜像在对应容器内生成 deploy key，控制面只经 `/status` 接收公钥；注册后以
  `control/provider-ready` marker放行 checkout。`git` workspace依赖镜像内 SSH配置；`blank` workspace不接触
  Git provider。
- 删除 `repo`/`git` environment 先做只读 Git 状态检查，确认后才执行删除。`purge=false` 保留 instance
  数据目录，`purge=true` 删除整个 instance 目录。
- Deployment reconcile 使用确定性容器名：pull image、创建 data root、替换容器并以
  `unless-stopped` 启动。purge 额外删除托管数据目录。
- 长操作只在进程内 operation store 保存 `queued/running/failed` 状态；进程重启后不恢复。
- 镜像内 `workspace-deploy-key` s6 oneshot对所有 workspace无条件生成或复用 deploy key；
  `workspace-bootstrap` s6 oneshot按容器环境自动执行 checkout和 open-path helper；
  `workspace-agent` 只暴露 `/status`、`/git-state`，通过 control marker观察 bootstrap，
  并直接执行只读 Git查询。控制面不得通过 Podman exec调用镜像 helper。

## Web 契约

应用固定单 worker，监听 `127.0.0.1:8003`。JSON 错误格式为 `{"error": "..."}`，Dashboard 是浏览器
状态的唯一来源。当前 API：

- `GET /api/dashboard`
- `PUT /api/tokens/{provider}`
- `POST /api/workspaces/{workspace}/instances`
- `GET /api/workspaces/{workspace}/hosts/{host}/instances/{instance}/logs`
- `DELETE /api/workspaces/{workspace}/hosts/{host}/operations/{instance}`
- `DELETE /api/workspaces/{workspace}/hosts/{host}/instances/{instance}`
- `POST /api/deployments/{deployment}/hosts/{host}/deploy`
- `GET /api/deployments/{deployment}/hosts/{host}/logs`
- `DELETE /api/deployments/{deployment}/hosts/{host}`
- `DELETE /api/deployments/{deployment}/hosts/{host}/operations`

Web UI 只在 operation 为 `queued` 或 `running` 时轮询。日志按需读取最近 2000 行，不流式推送。
失败 operation 可显式清除；运行中的 operation 不可隐藏。不要增加 SSE、前端 optimistic state、
OpenAPI 页面、远程监听或多 worker。

## 安全边界

- Rootful Podman socket 等价于 host root 权限；SSH host key verification 必须开启。
- Provider token 只存在于配置读取结果或进程内存，不得经 API 返回、写日志或回写配置。
- `controller/__init__.py` 必须注入 `truststore`，HTTPS provider 使用系统 CA 且不得关闭 TLS 校验。
- Repository deploy private key 只能在对应开发容器内生成和保存，不得进入控制面内存或日志。
- Agent UDS只存在于 mode `0700` 的逐实例 `control/`，经 OpenSSH StreamLocal访问，不发布 TCP端口；
  provider token不得进入容器。
- 登录 keypair 是仓库内固定的内网凭据；应用和容器端口均不得暴露到非可信网络。
- 用户 volume 和 secret mount 不得覆盖控制面保留 mount tree。

## 变更规则

- 先修改 [`DESIGN.md`](DESIGN.md) 中受影响的边界或流程，再同步代码、测试和本文约束。
- 修改开发镜像 host contract 时同步更新 [`../images/dev/AGENTS.md`](../images/dev/AGENTS.md)；
  修改 sidecar 或 LLM deployment 时同步对应目录的 `AGENTS.md`。
- 一次性同步、清理和修复操作放进 `tools/` 的单用途 Python CLI，不增加 Web endpoint、UI state 或
  常驻后台任务。
- 优先测试公开行为和跨模块契约，不绑定私有实现。
