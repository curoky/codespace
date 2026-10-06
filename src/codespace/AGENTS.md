# Control Plane

此目录拥有运行在 macOS localhost 上的控制面。进程入口一次性加载 immutable desired
state，通过 OpenSSH 管理 Linux Host 上的 rootful Podman；已部署资源只从 labels 与
inspect 数据还原。

## Ownership

| Path | Responsibility |
| --- | --- |
| `config.py` | YAML schema、layer merge、placement 校验与最终 spec 生成 |
| `resources.py` | Workspace/Service 共用 identity、container name、labels 与业务错误 |
| `services.py` | Service metadata/spec 及 actual inventory 解码 |
| `operations.py` | process-local operation 状态与异常摘要 |
| `control.py` | inventory、deploy/remove、日志、tunnel 与 operation 编排 |
| `cli.py` | Typer 命令树和 Web server 入口接线 |
| `web/` | localhost HTTP boundary、dashboard read model 与静态 UI |
| `workspaces/` | Workspace domain、lifecycle、provider、Agent client 与 SSH route |
| `runtime/` | OpenSSH、Podman 与 Host filesystem primitives |
| `maintenance/` | 可审计的 secret/resource sync 与 prune 命令 |

依赖方向固定为 `web -> control -> workspaces/services -> runtime`。`control.py` 负责跨域
顺序和进度，不下沉 provider、SSH 或 Podman 细节；`runtime/` 不读取 `Config`。

## State Contracts

- 控制面只读取 `/Users/x/.config/codespace/config.yaml`，并在进程入口一次性转换为 immutable
  Pydantic model。`config.example.yaml` 展示完整 schema；真实 token 与 secret 不得提交。
- `config.py` 只描述 desired state。不要用当前配置补齐旧容器缺失的 labels、source、image
  或 path，也不要在 inventory 时隐式迁移。
- `hosts` 声明 SSH Host、forwarded environment 与 Host container override；`projects` 和
  `services` 的 `hosts` 只声明 placement。Host 差异写入 Host，资源差异写入 Project 或
  Service。
- Project container layer 按 `project_defaults -> Host -> Project` 合并；Service 按
  `Host -> Service` 合并。environment 按 key 合并，volume 按 source 或 target 替换，
  其他 collection 由下层整体替换。
- 配置使用受支持的 Compose service 语义；到 podman-py kwargs 的映射只属于
  `runtime/container.py`。
- `Resource` 是所有写操作的统一地址。新增 identity 字段时，必须同步检查 name、labels、
  inventory 解码、operation key、API path 和测试 fixture。
- `OperationStore` 只支持 single-process、single-worker。成功 operation 删除，失败
  operation 保留到显式 dismiss；不得暗示持久恢复、跨 worker 协调或 rollback。
- Host 持久数据统一位于 `$HOME/codespace/`。普通 remove 保留资源目录，只有 purge 删除；
  Workspace encryption 只覆盖业务数据，不隐式覆盖 control socket 或 IDE cache。
- 配置 schema 变化必须同步 `config.example.yaml` 与 `tests/test_config.py`；涉及最终 runtime
  spec 时再覆盖对应 lifecycle/runtime 测试。

## Web And Operations

- `web/app.py` 只负责输入 model、route、error mapping、static mount 与 `ControlPlane`
  lifespan；`web/dashboard.py` 把一次 live inventory 与 desired config 投影为 browser read
  model，Web 层不拥有 lifecycle 或持久状态。
- 写操作先同步 `queue`，通过 placement、token 与 duplicate-operation 校验后才注册
  `BackgroundTasks`。Workspace 和 Service route 都通过 `Resource` 进入控制面，不在 Web 层
  拼接 container name、SSH alias 或 data path。
- `ResourceNotFound`、`ResourceConflict` 与输入错误分别映射 404、409、422；未知错误只通过
  `describe_error` 返回稳定摘要。
- dashboard 保留 per-Host failure。SSH 建连失败是 `offline`，连接后的 inventory 失败是
  `error`，单个 Host 失败不阻塞其他 Host。
- Dashboard inventory 同步读取运行中 Workspace 对应的 Host 本地 image ID，与容器 image
  ID 比较；镜像拉取由 support Service 负责，Web 不访问 registry、不维护定时任务或缓存，
  其他 Service 不参与比较。
- static UI 没有独立构建步骤。API payload 或交互变化必须同步 route、dashboard projection、
  client 与 `tests/web/`。
- 应用退出时必须关闭 `ControlPlane`，统一释放 ControlMaster、socket forward 与 TCP tunnel。

## Workspace Lifecycle

- Workspace identity、container name、SSH alias、deploy-key title 与 deterministic SSH port
  由 `workspaces/__init__.py` 集中派生，其他层不得另写算法。
- create 在远端写入前检查 identity、container name 与 SSH port 冲突；现有 Workspace 不被
  replace。runtime-only environment、source metadata 与 loopback SSH publication 只在创建
  最终 spec 时注入，不写回配置。
- Project `source` 是 repository 列表；空列表创建空 Workspace，默认 `open_path` 是第一项的
  checkout path。provider private key 在容器中生成，控制面只接收 public key，向所有 provider
  repository 注册 deploy key 后再调用 `provider-ready`；token 不进入 Workspace。Agent ready
  后才能写 macOS SSH route，失败时保留现场和 operation error。
- Workspace rebuild 强制 pull 最新 image，成功后才替换 container，并复用已部署数据；provider
  Workspace 必须替换 ephemeral deploy key 后再放行 checkout。source 或 encryption 变化必须
  delete 后重新 create，不在 rebuild 中迁移。
- 删除检查通过 Agent 读取 Git 状态，不启动或修改已停止 Workspace。删除 provider
  Workspace 时先成功撤销 deploy key；普通 remove 保留 data，purge 才删除。
- Service apply 使用 replace reconciliation：先 pull image 并准备数据，再移除旧 container、
  创建新 container。失败保留当前现场，不恢复旧 container。Service remove 允许资源尚未部署，
  Workspace remove 要求目标 container 存在。
- SSH route 原子写入 `/Users/x/.ssh/codespace/workspaces/`，并复用系统 OpenSSH config、
  Host authentication 与 host-key verification。
- 容器端 Agent 位于 `platform/container/workspace/agent/`。修改 endpoint、payload、state 或
  timeout 时同步 client、server、lifecycle 和 `tests/workspaces/test_agent.py`，不保留旧协议
  fallback。

## Runtime And Connectivity

- `runtime/container.py` 是 Compose-like config 到 podman-py kwargs 的唯一映射边界。新增
  container 字段时同步 `ContainerLayer`、merge、validation、mapping、example config 和测试。
- volume source 为绝对路径或 `${RESOURCE_DATA}` 时是 Host bind，其他 source 是 named
  volume；placeholder 结果不得逃逸当前 resource data root。
- idmap 只适用于 Host bind；通过 podman-py 的 extended volume mode 传递给 rootful
  Podman。Workspace 密文 bind 把 Host `5230:5230` 映射为容器 `1001:1001`。
- 所有 publication 必须绑定 Host loopback。secret 必须预先存在；缺失时 fail-fast，不降级为
  environment 或明文文件。
- 同一 Host 的 container 通过默认 Podman network DNS 访问
  `codespace-service-<service>:<target-port>`。该 network 是 Host-local 共享信任域，DNS name
  不是访问控制；Service replacement 期间调用方必须容忍短暂不可用。
- `container.ports` 只声明固定 Host publication，`tunnel_ports` 只声明 Web UI 可打开的
  container TCP port。未显式 publication 的 tunnel port 使用 Host loopback 随机端口；最终
  port 冲突由 Podman apply 结果判定。
- 普通 container remove 不删除数据。purge 使用受管 helper container，并再次验证目标属于
  预期 data root。
- 每个 Host 只有一个复用的 OpenSSH ControlMaster，用于 command 与 Unix socket forwarding；
  用户 TCP tunnel 使用独立 process，并由 transport 统一关闭。
- `runtime/` 接收已解析参数，不读取 `Config`，不拥有 Workspace/Service lifecycle，也不接管
  OpenSSH credential、proxy chain 或配置解析。

## Security Boundaries

- provider token 只存在于 macOS 配置和控制面内存，不进入 Workspace；deploy private key 在
  Workspace 内生成且不离开容器，Agent 只返回 public key。
- Workspace Agent 只监听 bind-mounted Unix socket，不开放 TCP。Workspace SSH 只发布到 Host
  loopback，Project/Service tunnel 必须通过配置 allowlist。
- encryption secret mount 必须显式写入最终 container config；缺少 key 时 fail-fast，不降级为
  明文 Workspace。
- Host rootful Podman socket 等同 Host root 权限，只能挂载给明确拥有 Host maintenance
  职责的 Service。

## Maintenance

- `maintenance/` 命令先完成 discovery 并输出可审计计划，默认 dry-run；只有显式 `--apply`
  修改远端状态。plan 与 apply 共用 decision code。
- Host/repository 可以并发处理，但任一 inventory 失败都必须使命令失败；不得基于不完整状态
  继续删除其他对象。
- resource sync 先 pull image，再按 Host 最新 digest 判断是否重填 volume；digest marker 与
  payload 写入属于同一次成功结果。secret 检查和可选写入使用同一 Host connection。
- prune 只处理 Codespace 可证明拥有且不再 active 的 data path 或 deploy key。未配置 provider
  token 时 warning 并跳过，不把缺少权限解释成对象不存在。

## Operations

```bash
task sync
task serve
task serve:bg

task secrets:sync -- [--apply]
task resources:sync -- [--apply] [--force]
task workspaces:prune -- [--apply]
task deploy-keys:prune -- [--apply]
```

维护任务默认只输出完整计划；`--apply` 才执行计划。CLI 参数必须放在 Task 的 `--` 之后。

## Validation

按改动范围先运行定向测试：

```bash
uv run pytest tests/test_config.py tests/test_operations.py tests/test_control.py \
  tests/test_lifecycle.py tests/services tests/web tests/workspaces tests/runtime \
  tests/maintenance
```

完成后运行 `task check:full`。
