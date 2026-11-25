# Control Plane

## Scope

在 macOS localhost 通过系统 OpenSSH 管理 Linux Host；只支持 single-process/single-worker，
operation 为进程内状态，不承诺持久恢复或跨 worker 协调。工具链以
[项目声明](../../pyproject.toml)/uv lock 为准，不使用系统 Python。

[config.py](config.py) 拥有 schema/合并/spec，[resources.py](resources.py) 拥有 identity
与业务错误，[control.py](control.py) 编排 domain；runtime 只提供 primitives，Web 只做
model/route/error mapping/lifespan/dashboard projection。

## Contracts

- 不修改已加载配置；frozen Pydantic 不保证嵌套 collection 不可变。Host 拥有 SSH、
  forwarded environment 和 container override，Project/Service 只声明差异与 placement；
  合并规则以 `_merge_container_layers` 为准，runtime-only 输入只注入最终 spec，不写回配置。
- identity 从 `Resource` 派生，不在调用方另写算法；变化须覆盖 name/labels/inventory/
  operation key/API path。写操作先占用 operation；成功记录删除，失败保留到 dismiss
  或下次操作。Web 后台操作同步 queue 并校验后才注册，同步删除失败仍向 HTTP 抛出，
  业务错误统一映射，未知错误通过 `describe_error` 摘要。
- inventory 支持空 Host 集合并隔离 per-Host failure：建连失败为 offline，读取失败为
  error。运行中 image ID 只与 Host 本地 image 比较，不查 registry 或增加 Web cache；
  后台 image 拉取由 support Service 负责。
- provider private key 只留在 Workspace，控制面只接收 public key；token 留在 macOS
  配置/内存。publication 只绑定 Host loopback，tunnel 只开放 allowlist port；缺 secret
  直接失败，不降级明文。Host rootful Podman socket 只授予明确的 maintenance owner。
- [runtime/container.py](runtime/container.py) 是字段到 podman-py kwargs 的唯一映射。
  绝对路径与 `${RESOURCE_DATA}` source 为 bind，其余为 named volume；placeholder 不得
  逃逸 data root，named source 不可重复以免 SDK 映射丢项，bind 可挂不同 target。
  encryption 只覆盖业务数据，不覆盖 control socket 或 IDE cache。

## Main Flows

[Workspace lifecycle](workspaces/lifecycle.py) 在 create 检查 identity/name/SSH port 冲突，
不替换已有实例；准备最终 spec/image/data 后创建 container。provider source 等待 Agent
public key，注册全部 repository 后调用 provider-ready 放行 checkout；Agent ready 后发布
SSH route。无 provider source 时直接 bootstrap，无 source 时准备空 Workspace。

rebuild 强制 pull，准备成功后替换 container 并复用 data，但重新注册 provider key；
source/encryption 变化要求 delete/create。Service apply 使用 replace reconciliation，
remove 允许尚未部署；Workspace remove 要求实际容器存在。

删除前通过 Agent 检查全部已部署 source 的 Git 状态，不为检查启动或修改已停止实例。
先解析全部 credential，再尽力撤销 deploy key；撤销失败不阻止删除，因为唯一 private key
随容器销毁，遗留 public key 交给 prune。

[maintenance](maintenance/) 默认 dry-run，plan/apply 共用 decision code；全部 Host
discovery 成功并输出完整计划后，显式 `--apply` 才改业务资源。初次 SSH 握手串行以避免
共享 GSSAPI ProxyJump 认证冲突，其余工作可并发；任一 inventory 失败使命令失败。
prune 只处理能证明受管且不再 active 的对象，缺 token 时 warning/跳过，不视为对象不存在。

## Runtime I/O

- **Reads**：只读 `~/.config/codespace/config.yaml`，复用系统 OpenSSH authentication、
  proxy chain/host-key verification；远端读取 inventory/logs、声明的 environment 与 Git 状态。
- **Local Writes**：[SSH route](workspaces/ssh.py) 原子写入 `~/.ssh/codespace/workspaces/`；
  inventory 也会刷新，删除时移除对应项。[后台启动脚本](../../scripts/run-control-plane.sh)
  同步项目依赖、停止已有 Codespace server、替换日志/PID；启动失败保留日志并清理 PID。
- **Host Writes**：修改 container 和 Host 登录用户 `$HOME/codespace/` 下的 data；普通
  remove 保留 data，purge/prune 用受管 helper 再验证目标才删除。dry-run discovery 也可能
  初始化数据根，范围见 [host.py](runtime/host.py)/[container.py](runtime/container.py)。
  [secrets sync](maintenance/secrets.py) 上传并替换声明的 Podman secret；
  [resources sync](maintenance/resources.py) 清空旧 volume payload，按 pull 后的 digest
  重算计划，payload/marker 同次成功发布，检查与写入复用同一 client。
- **Network**：SSH/registry 目标由配置决定；[provider](workspaces/provider.py)/
  [key prune](maintenance/keys.py) 访问 GitHub/GitLab，注册 public deploy key 授予读写
  权限或查询/撤销 key，不上传 private key；checkout 在 Workspace，不在 client。
- **Results & Failure**：以 Agent ready/Service apply 完成判定部署成功；失败不恢复旧容器。
  关闭释放 ControlMaster、socket forward/TCP tunnel，operation failure 不代表可持久恢复。

## Pitfalls

Podman network DNS 是 Host-local 共享信任域，不是访问控制；名称可解析不保证隔离或 ready，
调用方须容忍 Service replacement 的短暂不可用。

## Validation

[tests](../../tests) 按 config/operations/lifecycle、workspaces/services/runtime/web/maintenance
选择定向测试；schema/spec 变化同步 [配置示例](../../config.example.yaml) 与映射测试，API
变化同步 dashboard/client，Agent 协议变化同步 [client](workspaces/agent.py)/server 与双方
协议测试。类型检查不依赖增量缓存。维护 Task 参数放在 `--` 后，不为文档检查执行 apply。
