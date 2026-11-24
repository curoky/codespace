# Control Plane

## Scope

控制面在 macOS localhost 运行，通过 OpenSSH 管理 Linux Host。启动时加载 frozen Pydantic
配置；frozen 不保证嵌套 collection 不可变，业务代码不得修改已加载配置。Python 与依赖由
项目版本声明和 uv lock 管理，不使用系统 Python。

`config.py` 拥有 schema、合并和 spec；`resources.py` 拥有统一 identity 与业务错误；
`control.py` 编排跨域操作；`operations.py` 记录进程内状态。Workspace/Service domain、
runtime primitives、Web boundary 和 maintenance 分别留在所属模块。

## Contracts

- 只读取 `~/.config/codespace/config.yaml`。`config.example.yaml` 展示 schema；schema
  变化同步示例与配置测试，最终 spec 变化覆盖 lifecycle/runtime 测试。
- Host 拥有 SSH、forwarded environment 和 container override；Project/Service 只声明资源
  差异与 placement。Project layer 按 defaults、Host、Project 合并；Service 按 Host、Service
  合并。environment 按 key、volume 按 source 或 target 替换，其余 collection 整体替换。
- desired spec 的 image/platform 从 container 派生；actual 对象从部署 metadata 读取。
  `Resource` 统一写操作地址；identity 变化检查 name、labels、inventory、operation key、
  API path 与 fixture，不在调用方另写派生算法。
- 写操作在任何副作用前占用 operation；create/apply/rebuild 校验最终 runtime spec 与
  secret 后才 pull/prepare/replace。成功记录删除，失败保留到 dismiss 或下一次操作；同步删除仍向
  HTTP 抛出失败。只支持 single-process、single-worker，不承诺持久恢复或跨 worker 协调。
- Web 只负责 model、route、error mapping、lifespan 和 dashboard projection；后台写操作
  先同步 queue，token/placement/冲突校验后才注册。404/409/422 使用统一业务错误，
  未知错误通过 `describe_error` 摘要；API 变化同步 dashboard、静态 client 与 Web tests。
- inventory 支持空 Host 集合，并隔离 per-Host failure：建连失败是 offline，连接后的读取
  失败是 error。运行中 Workspace 的 image ID 只与 Host 本地 image 比较，不访问 registry
  或引入 Web cache；image 拉取由 support Service 负责。
- Workspace create 检查 identity、name 与 SSH port 冲突，不替换已有实例。runtime-only
  environment、metadata 与 loopback SSH publication 只注入最终 spec，不写回配置。
- provider private key 在 Workspace 生成且不离开容器；控制面只接收 public key，向全部
  repository 注册后调用 provider-ready。token 只留在 macOS 配置与内存。Agent ready 后
  才发布 client SSH route；空 source 创建空 Workspace。
- rebuild 强制 pull 最新 image，准备成功后替换 container 并复用数据；provider key 必须
  重新注册后放行 checkout。source/encryption 变化要求 delete/create，不在 rebuild 中迁移。
- 删除前通过 Agent 读取 Git 状态，不启动或修改已停止 Workspace。先解析全部已部署 source
  的 credential，再尽力撤销 deploy key；撤销失败不阻止删除，因为唯一 private key 随容器
  销毁，遗留 public key 由 prune 清理。普通 remove 保留 data，purge 才删除。
- Service apply 使用 replace reconciliation，失败不恢复旧容器；remove 允许尚未部署。
  Workspace remove 要求实际容器存在。持久数据属于 Host 的 `$HOME/codespace/`；
  encryption 只覆盖业务数据，不覆盖 control socket 或 IDE cache。
- SSH route 原子写入 `~/.ssh/codespace/workspaces/`，复用系统 OpenSSH authentication、
  proxy chain 与 host-key verification。应用关闭时释放 ControlMaster、socket forward 和
  独立 TCP tunnel。Agent endpoint/payload/state/timeout 变化同步 client/server 与协议测试。
- Compose-like 字段到 podman-py kwargs 的唯一映射在 `runtime/container.py`。字段变化同步
  schema、merge、validation、mapping、示例和测试；runtime 不拥有应用配置或 lifecycle。
- 绝对路径与 `${RESOURCE_DATA}` source 是 bind，其余是 named volume；placeholder 不得
  逃逸 data root。bind 可挂到不同 target，named source 不能重复，避免 source-keyed SDK
  映射静默丢项。purge 使用受管 helper，并再次验证目标属于预期 data root。
- publication 只绑定 Host loopback；secret 必须预先存在，缺少 key 不降级成明文。
  tunnel 只开放 allowlist port，无固定 publication 时使用随机 loopback port。
- Agent 只监听 bind-mounted Unix socket。Host rootful Podman socket 等同 root 权限，只给
  明确拥有 Host maintenance 职责的 Service。

## Pitfalls

- 默认 Podman network DNS 是 Host-local 共享信任域，不是访问控制；调用方须容忍 Service
  replacement 的短暂不可用。
- maintenance 默认 dry-run，plan/apply 共用 decision code；全部 Host discovery 成功并输出
  完整计划后才写入。初次 SSH 握手串行，避免共享 GSSAPI ProxyJump 并发认证冲突；其余
  discovery、apply 和 provider HTTP 可并发，任一 inventory 失败使命令失败。
- resource sync 先按本地 image 输出计划，apply pull 全部 Host image 后按新 digest 重算；
  payload 与 digest marker 同次成功发布。检查和写入复用同一 Podman client。
- prune 只处理能证明属于 Codespace 且不再 active 的 data/deploy key；缺 token 时 warning
  并跳过，不能解释成对象不存在。

## Validation

定向测试位于 `tests/{workspaces,services,runtime,web,maintenance}/` 与根配置/operation/
lifecycle tests。维护命令入口见 `Taskfile.yaml`；CLI 参数放在 Task 的 `--` 之后，
只有显式 `--apply` 才修改远端。
