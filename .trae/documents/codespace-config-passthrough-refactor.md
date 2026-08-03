# Codespace 配置端到端化与容器参数透明转发

## Summary

系统梳理 `codespace/client/` 中「配置 → 容器启动参数」链路上的所有默认值与转换，把
**软默认值**（代码里用 `or` / 常量隐式填充的值）改为显式配置，把当前 **硬编码的容器 run
flags** 上移到配置并近似原样透传给 `podman run`，同时明确保留少数「跨组件契约常量」为内部
常量。目标是让 `config.yaml` 成为端到端事实来源，`runtime.create_container` 内部不再持有隐式
默认值，配置到容器参数之间只做必要的、契约驱动的映射。

范围锁定（依据澄清答复）：

- **仅消除软默认值**：`user`/`uid:gid`/`/workspace` 挂载点/SSH 端口范围/确定性命名等身份类
  契约常量保持为内部常量，不进配置。
- **仅去除硬编码常量**：容器 run flags 用结构化强类型字段承载，不做任意 kwargs 直通。
- **全部入配含契约**：`cap_add`、`security_opt`（含 `disable`/`seccomp=unconfined`）、
  `pids_limit`、`ulimits`、额外 `mounts`（krb5）、额外 `env` 全部移入配置透传。
- **全局 + 覆盖**：新增顶层 `container:` 全局默认块，允许 `hosts.<host>.container` 与
  `projects.<project>.container` 按 key 覆盖（浅层 replace，非深合并）。

## Current State Analysis

### 链路概览

`config.yaml` → `Config`/`HostConfig`/`ProjectConfig`（[config.py](file:///Users/x/workspace/devspace/codespace/client/config.py)）
→ `CodespaceService._create`（[service.py](file:///Users/x/workspace/devspace/codespace/client/service.py#L191-L296)）
→ `runtime.create_container`（[runtime.py](file:///Users/x/workspace/devspace/codespace/client/runtime.py#L222-L301)）→ `podman.containers.run`。

### 现存「软默认值」（代码隐式填充）

| 位置 | 现状 | 分类 |
| --- | --- | --- |
| [config.py:57-61](file:///Users/x/workspace/devspace/codespace/client/config.py#L57-L61) `resolved_podman_socket` | `self.podman_socket or PODMAN_SOCKET` | 软默认 → 显式化 |
| [config.py:186-188](file:///Users/x/workspace/devspace/codespace/client/config.py#L186-L188) `project_image` | `project.image or self.default_image` | 配置级默认，保留（`default_image` 本就是显式配置） |
| [config.py:140-142](file:///Users/x/workspace/devspace/codespace/client/config.py#L140-L142) `resolved_open_path` | `self.open_path or workspace_open_path(self.repo)` | 类型派生，保留（非隐式常量） |
| [runtime.py:258](file:///Users/x/workspace/devspace/codespace/client/runtime.py#L258) label platform | `platform or "native"` | sentinel 派生，集中到 models |
| [HostConfig.type](file:///Users/x/workspace/devspace/codespace/client/config.py#L33) / `gpu` | `"ssh"` / `False` | 保留（枚举/布尔的合法缺省，非隐式常量） |
| [ProjectConfig.type](file:///Users/x/workspace/devspace/codespace/client/config.py#L84) | `"repo"` | 保留 |

### 现存「硬编码容器 run flags」（config 无法影响）

集中在 [runtime.py:250-297](file:///Users/x/workspace/devspace/codespace/client/runtime.py#L250-L297)：

- `cap_add=["NET_RAW", "SYS_ADMIN"]`
- `security_opt=["disable", "seccomp=unconfined"]`（CLAUDE.md 契约）
- `pids_limit=-1`
- `ulimits=[{"Name": "memlock", "Soft": -1, "Hard": -1}]`
- 额外 bind mount `/etc/krb5.conf`（只读）
- `environment` 里的 `SSHD_PORT`（派生）/`SSHD_BIND`（bridge 派生）
- `devices=["nvidia.com/gpu=all"]`（由 `gpu: bool` 派生）

### 现存「转换」（config → run）

- `bridge = host_config.type == "podman-machine"`（[service.py:241](file:///Users/x/workspace/devspace/codespace/client/service.py#L241)）→ `network_mode`
- `parse_port_mapping` 端口解析（保留，属必要解析）
- `gpu: bool` → `devices`（保留 CDI 字符串为命名常量）

### 发现的配置漂移（需一并修复）

用户实际 `~/.config/codespace/config.yaml` 使用 `published_ports:`，而代码 schema 字段是
`ports`（[config.py:91](file:///Users/x/workspace/devspace/codespace/client/config.py#L91)）且
`extra="forbid"`——当前该配置无法通过校验。属于本次「端到端配置」要消除的 config↔code 漂移。

### 保留为内部契约常量（不进配置，依据「仅消除软默认值」）

[models.py:19-28](file:///Users/x/workspace/devspace/codespace/client/models.py#L19-L28)：
`CONTAINER_USER="x"`、`CONTAINER_UID=5230`、`WORKSPACE_MOUNT="/workspace"`、
`WORKSPACE_DIR_NAME`、`PODMAN_SOCKET`（改为仅作显式 fallback 语义见下）、
`SSH_PORT_START/COUNT`、确定性命名与 label 契约、`nvidia.com/gpu=all` CDI 字符串。

## Proposed Changes

### 1. 新增结构化容器运行配置模型（[config.py](file:///Users/x/workspace/devspace/codespace/client/config.py)）

新增强类型模型（`extra="forbid"`），承载可透传的 run flags：

```python
class Ulimit(BaseModel):
    name: str
    soft: int
    hard: int

class ExtraMount(BaseModel):
    source: str      # 绝对路径校验
    target: str      # 绝对路径校验
    read_only: bool = False

class ContainerConfig(BaseModel):
    cap_add: list[str]
    security_opt: list[str]
    pids_limit: int
    ulimits: list[Ulimit]
    mounts: list[ExtraMount] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
```

设计说明（依据「仅去除硬编码常量」）：字段为强类型、语义清晰，**不做任意 kwargs 直通**；
`mounts`/`env` 允许为空列表/空字典（这是「无额外项」的显式表达，不是隐式默认）。
`cap_add`/`security_opt`/`pids_limit`/`ulimits` 为必填——顶层 `container:` 必须显式声明，
消除代码内隐式默认。

### 2. 全局 + 覆盖分层（[config.py](file:///Users/x/workspace/devspace/codespace/client/config.py)）

- `Config` 新增必填顶层字段 `container: ContainerConfig`（全局默认）。
- `HostConfig` 新增可选 `container: ContainerOverride | None`。
- `ProjectConfig` 新增可选 `container: ContainerOverride | None`。
- `ContainerOverride`：与 `ContainerConfig` 同形但所有字段可选，用于按 key 覆盖。
- 新增解析方法 `Config.resolved_container(project_id) -> ContainerConfig`：按
  **project 覆盖 host 覆盖 global** 的顺序做 **浅层 key 级 replace**（列表/字典整体替换，
  不深合并），任一被覆盖 key 取最靠近 project 的显式值；未覆盖 key 取全局值。fail-fast：
  全局块缺字段直接 pydantic 报错。

配置示例（写入 CLAUDE.md）：

```yaml
container:
  cap_add: [NET_RAW, SYS_ADMIN]
  security_opt: [disable, seccomp=unconfined]
  pids_limit: -1
  ulimits:
    - {name: memlock, soft: -1, hard: -1}
  mounts:
    - {source: /etc/krb5.conf, target: /etc/krb5.conf, read_only: true}
  env: {}

hosts:
  gpu-box:
    gpu: true
    container:
      cap_add: [NET_RAW, SYS_ADMIN, SYS_PTRACE]   # 覆盖该 host
```

### 3. `podman_socket` 软默认显式化（[config.py:57-61](file:///Users/x/workspace/devspace/codespace/client/config.py#L57-L61)）

保留 `PODMAN_SOCKET` 常量，但语义收敛为「文档记录的标准路径」而非代码隐式回退：
- 保持 SSH host 未写 `podman_socket` 时使用 `PODMAN_SOCKET`（CLAUDE.md 已文档化，属显式契约
  默认，非隐藏软默认）。**决策**：此项按「配置级默认」保留，与 `default_image` 同类；在
  Assumptions 中记录，若需进一步显式化再单独处理，避免破坏 `home:` 空 host 的既有便利。

### 4. `platform` sentinel 集中（[models.py](file:///Users/x/workspace/devspace/codespace/client/models.py) / [runtime.py:258](file:///Users/x/workspace/devspace/codespace/client/runtime.py#L258)）

新增 `models.platform_label(platform: ImagePlatform | None) -> PlatformSelection`，把
`platform or "native"` 的 `None → "native"` 转换收敛为单一函数，`create_container` 与
`service._create`（[service.py:263](file:///Users/x/workspace/devspace/codespace/client/service.py#L263)）共用，消除散落的字面量默认。

### 5. `create_container` 去硬编码、改透传（[runtime.py:222-301](file:///Users/x/workspace/devspace/codespace/client/runtime.py#L222-L301)）

- 函数签名新增 `container: ContainerConfig` 参数，移除内部硬编码的
  `cap_add`/`security_opt`/`pids_limit`/`ulimits` 字面量与 krb5 mount 字面量。
- `podman.containers.run` 的对应 kwargs 直接来自 `container` 字段（近似原样转发）：
  - `cap_add=container.cap_add`
  - `security_opt=container.security_opt`
  - `pids_limit=container.pids_limit`
  - `ulimits=[{"Name": u.name, "Soft": u.soft, "Hard": u.hard} for u in container.ulimits]`
  - `environment = {**container.env, "SSHD_PORT": str(port), ...}`（派生 env 最后写入，
    防止被配置覆盖；若配置 env 含保留键则 fail-fast 报错）
  - `mounts` = workspace bind（契约常量）+ `container.mounts` 透传（krb5 现由配置提供）
- 保留为内部契约常量/派生：workspace bind、`network_mode`（由 bridge 派生）、`SSHD_PORT`/
  `SSHD_BIND`（派生）、`devices`（由 `gpu` 派生，CDI 串为命名常量 `CDI_ALL_GPUS`）。
- `# noqa: S104`（`0.0.0.0`）保留。

### 6. `network_mode` 转换收敛（[config.py](file:///Users/x/workspace/devspace/codespace/client/config.py) / [service.py:241](file:///Users/x/workspace/devspace/codespace/client/service.py#L241)）

在 `HostConfig` 增加 `network_mode` / `is_bridge` 属性，把
`host_config.type == "podman-machine"` 的判断从 service 内联移到 host 模型，service 只读取
语义化属性，减少「配置 → run」转换分散。

### 7. `service._create` 组装透传（[service.py:226-243](file:///Users/x/workspace/devspace/codespace/client/service.py#L226-L243)）

`create_container(...)` 调用处新增 `container=self.config.resolved_container(project_id)`；
`bridge=` 改为读 host 属性；其余不变。

### 8. 修复 `ports` → `published_ports` 命名漂移（[config.py:91](file:///Users/x/workspace/devspace/codespace/client/config.py#L91) 及调用方）

**决策**：将 schema 字段 `ports` 重命名为 `published_ports`，与用户实际配置及「端到端显式」
诉求一致。同步更新：
- [config.py](file:///Users/x/workspace/devspace/codespace/client/config.py) 字段名、`_validate_ports`、`project_ports`（保留方法名或改
  `project_published_ports`，二选一，计划取 `project_ports` 不变以缩小改动面，仅改配置键名）。
- CLAUDE.md 配置说明中的 `ports` 描述。
- 相关测试。

### 9. 文档同步（[codespace/CLAUDE.md](file:///Users/x/workspace/devspace/codespace/CLAUDE.md)）

依据「全部入配含契约」，把 `security_opt`、`cap_add`、`pids_limit`、`ulimits`、krb5 挂载从
「Host 契约 / 环境生命周期」的固定描述改写为「由配置 `container:` 块提供，控制面原样转发」，
新增 `container:` 全局块与 `hosts/projects` 覆盖说明，更新 `published_ports` 键名。

## Assumptions & Decisions

1. **身份/命名契约常量不进配置**（`CONTAINER_USER`、`5230:5230`、`/workspace`、SSH 端口
   范围、确定性 ID、label 键）——依据「仅消除软默认值」。
2. **强类型字段而非任意 kwargs 直通**——依据「仅去除硬编码常量」，`ContainerConfig` 只暴露
   明确字段，杜绝把 `containers.run` 全量 kwargs 开放。
3. **覆盖为浅层 key-level replace**，列表/字典整体替换，不做深合并——符合用户「简单直接、拒绝
   复杂自动探测」偏好；合并顺序 project > host > global。
4. **派生 env（`SSHD_PORT`/`SSHD_BIND`）在配置 env 之后写入**，配置若声明这两个保留键则
   fail-fast 报错，避免静默覆盖。
5. **`default_image` 与 `podman_socket` 的显式回退保留**：二者是「配置里可省略、由另一显式
   配置项/文档化标准路径补足」，非代码隐藏常量，保留以维持 `home:` 空 host 等既有便利。若后续
   要求彻底显式，再单独处理。
6. **`gpu: bool` 保留**，CDI 设备串 `nvidia.com/gpu=all` 作为命名常量 `CDI_ALL_GPUS`——它是
   条件能力开关的契约值，非「默认值」。
7. **`ports` 重命名为 `published_ports`**，与用户实际配置对齐；这是破坏性配置变更，仅影响本地
   个人配置与文档，无外部消费者。

## Verification

按 CLAUDE.md 验证顺序：

```bash
uv run ruff format --check codespace/client
uv run ruff check codespace/client
uv run mypy codespace/client
uv run pytest codespace/client/tests
uv lock --check
```

重点测试（新增/更新）：

- `tests/test_config_models.py`：`ContainerConfig`/覆盖合并（global/host/project 三层）、
  缺失全局字段 fail-fast、`published_ports` 键名、`env` 保留键冲突报错、`ExtraMount` 绝对
  路径校验。
- `tests/test_runtime.py`：`create_container` 用传入 `ContainerConfig` 组装 `containers.run`
  kwargs（断言 cap_add/security_opt/pids_limit/ulimits/mounts/env 与配置一致）；派生
  `SSHD_PORT`/`SSHD_BIND` 覆盖顺序；krb5 现来自配置 mounts。
- `tests/test_service.py`：`_create` 传入 `resolved_container(project_id)`；bridge 由 host
  属性派生。

手动核对：用本地 `~/.config/codespace/config.yaml`（补上顶层 `container:` 块、`ports` 改
`published_ports`）能通过 `load_config` 校验并成功创建容器。
