# Control Plane

## Scope

在 macOS localhost 运行控制面，通过系统 OpenSSH 管理 Linux Host；只支持 single-process、
single-worker，operation 是进程内状态，不承诺持久恢复或跨 worker 协调。
Python 与依赖由 [项目声明](../../pyproject.toml) 和 uv lock 管理，不使用系统 Python。

[config.py](config.py) 拥有 schema、合并和 spec，[resources.py](resources.py) 拥有统一
identity 与业务错误，[control.py](control.py) 编排跨域操作；Workspace/Service domain、
runtime primitives、Web boundary 和 maintenance 留在各自模块，不在 Web 重复业务逻辑。

## Contracts

- 启动后不修改已加载配置；frozen Pydantic 不保证嵌套 collection 不可变。schema 变化同步
  [配置示例](../../config.example.yaml) 与配置测试，最终 spec 变化覆盖 lifecycle/runtime tests。
- Host 拥有 SSH、forwarded environment 和 container override；Project/Service 只声明
  差异与 placement。合并次序和 collection 替换规则由
  [config.py](config.py) 的 `_merge_container_layers` 拥有，不能在 domain 再实现一套。
- desired spec 从 container 派生 image/platform，actual 对象只读部署 metadata。
  `Resource` 统一写操作地址；identity 变化检查 name、labels、inventory、operation key、
  API path 与 fixture，不在调用方另写派生算法。
- 写操作在任何副作用前占用 operation；校验最终 runtime spec 与 secret 后才准备部署。
  [operations.py](operations.py) 成功记录删除，失败保留到 dismiss 或下一次操作；同步删除
  仍向 HTTP 抛出失败，Service replace 失败不恢复旧容器。
- [Web](web/app.py) 只负责 model、route、error mapping、lifespan 和 dashboard projection。
  后台写操作先同步 queue，token/placement/冲突校验后才注册；404/409/422 用统一业务错误，
  未知错误通过 `describe_error` 摘要。API 变化同步 dashboard、静态 client 与 Web tests。
- inventory 支持空 Host 集合并隔离 per-Host failure：建连失败是 offline，建连后的读取
  失败是 error。运行中 Workspace 的 image ID 只与 Host 本地 image 比较，不查询 registry
  或引入 Web cache；后台 image 拉取由 support Service 负责。
- provider private key 在 Workspace 生成且不离开容器；控制面只接收 public key，token
  只留在 macOS 配置或内存。空 source 创建空 Workspace，不触发 provider 授权。
- [runtime/container.py](runtime/container.py) 是 Compose-like 字段到 podman-py kwargs
  的唯一映射；字段变化同步 schema、merge、validation、mapping、示例与测试。
  runtime-only environment、metadata 与 SSH publication 只注入最终 spec，不写回配置。
- 绝对路径与 `${RESOURCE_DATA}` source 是 bind，其余为 named volume；placeholder 不得
  逃逸 data root。bind 可挂不同 target，named source 不能重复，避免 source-keyed SDK
  映射静默丢项。encryption 只覆盖业务数据，不覆盖 control socket 或 IDE cache。
- publication 只绑定 Host loopback；secret 必须预先存在，缺少 key 不降级成明文。
  tunnel 只开放 allowlist port，无固定 publication 时用随机 loopback port。
- Agent 只监听 bind-mounted Unix socket；Host rootful Podman socket 等同 root 权限，
  只授予明确的 Host maintenance owner。Agent endpoint/payload/state/timeout 变化同步
  [client](workspaces/agent.py)、server 与双方协议测试。

## Main Flows

[Workspace lifecycle](workspaces/lifecycle.py) 拥有部署顺序：create 校验 identity、name、
SSH port 冲突后准备 image/data 并创建 container，不替换已有实例。provider source 等待
Agent public key，注册全部 repository 后调用 provider-ready 放行 checkout；Agent ready
后才发布 SSH route。无 provider source 直接 bootstrap。

rebuild 强制 pull 最新 image，准备成功后替换 container 并复用 data，但必须重新注册
provider key；source/encryption 变化要求 delete/create，不在 rebuild 中迁移。

删除前通过 Agent 读取全部已部署 source 的 Git 状态，不为检查启动或修改已停止实例。
先解析全部 credential，再尽力撤销 deploy key；撤销失败不阻止删除，因为唯一 private key
随容器销毁，遗留 public key 交给 prune。Workspace remove 要求容器存在；Service remove
允许尚未部署，apply 使用 replace reconciliation。

[maintenance](maintenance/) 默认 dry-run，plan/apply 共用 decision code；全部 Host
discovery 成功并输出完整计划后，显式 `--apply` 才写入业务资源。初次 SSH 握手串行，避免
共享 GSSAPI ProxyJump 并发认证冲突；其余 discovery、apply、provider HTTP 可并发，任一
inventory 失败使命令失败。prune 只处理能证明受管且不再 active 的 data/deploy key；缺
token 时 warning 并跳过，不把它视为资源不存在。

## Runtime I/O

- **Reads**：应用只读 `~/.config/codespace/config.yaml`；SSH 复用系统 OpenSSH config、
  authentication、proxy chain 与 host-key verification。远端读取 Podman inventory/logs、
  声明的 Host environment 与 Agent Git 状态；secret 来源由配置指定。
- **Local Writes**：[ssh.py](workspaces/ssh.py) 原子写入 `~/.ssh/codespace/workspaces/`，
  inventory 查询也会刷新 route，删除时移除对应项。不写回应用配置，运行期 token 只存内存。
  [后台启动脚本](../../scripts/run-control-plane.sh) 同步项目依赖、替换日志/PID，并停止
  已有 Codespace server；失败保留日志，PID 按实际启动结果清理。
- **Host Writes**：部署创建或替换 container，并准备 Host 登录用户的 `$HOME/codespace/`
  持久数据。普通 remove 保留 data，purge/prune 通过受管 helper 再验证目标才删除；范围
  见 [host.py](runtime/host.py) 与 [container.py](runtime/container.py)。dry-run discovery
  也可能初始化受管数据根，不能宣称完全零写入。
- **Maintenance Writes**：[secrets sync](maintenance/secrets.py) 上传声明的 secret 并创建
  或替换 Podman secret；[resources sync](maintenance/resources.py) 从 Resource image
  填充受管 volume，更新时清空旧 payload，成功后发布 digest marker。apply pull 全部 Host
  image 后按新 digest 重算计划，payload 与 marker 必须同次成功发布，检查和写入复用同一 client。
- **Network**：SSH/Podman 目标由 Host 配置确定，image 从声明的 registry 拉取。
  [provider.py](workspaces/provider.py) 和 [key prune](maintenance/keys.py) 访问 GitHub/GitLab
  API，查询、注册或撤销 repository deploy key；注册提交 public key 并授予读写权限，
  不上传 private key。checkout 由容器 Agent 执行，不在 client 克隆。
- **Results & Failure**：成功部署以 Agent ready/Service apply 完成及 operation 收敛为准；
  准备或替换失败保留真实现场，不自动恢复旧容器。关闭应用释放 ControlMaster、socket
  forward 与独立 TCP tunnel；operation failure 不是磁盘上的恢复日志。

## Pitfalls

默认 Podman network DNS 是 Host-local 共享信任域，不是访问控制；调用方须容忍 Service
replacement 的短暂不可用，不把名称可解析当作隔离或 ready 保证。

## Validation

定向测试见 [tests](../../tests) 的配置/operation/lifecycle 与
`workspaces/`、`services/`、`runtime/`、`web/`、`maintenance/`。维护任务入口见
[Taskfile.yaml](../../Taskfile.yaml)，CLI 参数放在 Task 的 `--` 后；不要为文档检查执行 apply。
类型检查不依赖增量缓存，保持本地与干净 CI 的范围一致。
