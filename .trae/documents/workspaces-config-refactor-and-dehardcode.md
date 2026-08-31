# 配置收敛（workspaces）与控制面去硬编码

## Context

在上一轮把 sidecar / llm 纳入控制面 deployment 体系后，顶层配置暴露出两个问题，本次一并处理：

1. **顶层键太散、语义错位**。`config.yaml` 顶层有 7 个键：`default_image`、`container`、`hosts`、
   `projects`、`deployments`、`tokens`、`secrets`。其中 `default_image` 和全局 `container`（NET_RAW/SYS_ADMIN、
   seccomp unconfined、host network、krb5 挂载等**开发容器专属**默认值）本质上只服务 `projects` 这类
   「开发容器」，却与 `deployments`（自包含部署容器）并列在顶层，导致 deployment 反而要用 `cap_add: []`
   `security_opt: []` `ulimits: {}` 去**反向清除**这些它并不需要的开发默认值。`projects` 这个名字也不够贴切
   ——它是「开发容器蓝图目录」，运行实例在代码里已叫 `environment`。
2. **控制面承载了本应下沉的命令逻辑**。[workspace.py](file:///Users/x/workspace/devspace/controller/workspace.py)
   里 clone / git-state / open-path 是多步 `execute` 序列，含「复用已有 checkout、空仓库标记、临时 clone 再 mv」
   等自适应分支，属于容器内 shell 逻辑却写在 Python 胶水层；
   [container.py](file:///Users/x/workspace/devspace/controller/container.py) 的
   `create_container` 与 `create_deployment_container` 有两段近乎重复的 podman-py run_options 组装。

目标产出：顶层键从 7 收敛到 5（`hosts` / `workspaces` / `deployments` / `tokens` / `secrets`）；`workspaces`
按 `defaults` + `items` 分层，开发默认值只作用于开发容器；deployment 天然不再继承开发默认值，从而删掉反向清除
样板；容器内命令序列下沉到 dev 镜像脚本，控制面回归薄胶水层。

## 关键决策（已定）

- **改名**：顶层 `projects` → `workspaces`（本轮已与用户确认；候选 blueprints/repos/devspaces
  均被排除）；结构为 `workspaces.defaults.{image, container}` +
  `workspaces.items.<id>`。`default_image` 并入 `workspaces.defaults.image`，全局 `container` 并入
  `workspaces.defaults.container`。`deployments` 保持顶层扁平自包含，形状不变。
- **命名边界**：改配置键、HTTP 路由（`/api/projects/*` → `/api/workspaces/*`）、UI 文案，以及内部 Python
  标识（`project_id`→`workspace_id`、`ProjectConfig`→`WorkspaceConfig`、`Operation.project`→`workspace` 等），
  保持整体一致。**因历史数据已清空、从零开始，无需迁移，故把改名做彻底**——包括此前一度冻结的三处
  on-container / on-host 取值也一并改齐：
  - 容器 label 字符串 `codespace.project` → `codespace.workspace`（`LABEL_PROJECT` → `LABEL_WORKSPACE`）；
  - `environment_id` 名称格式 `codespace-<host>-<workspace>-<instance>`；
  - 宿主数据目录布局 `~/codespace/<workspace>/<instance>` 等的占位符措辞。
    （`environment_id` 与宿主目录的实际生成逻辑本就用 workspace id 填充，仅措辞与 label 值需对齐。）
- **脚本下沉程度**：仅把**容器内**多步序列下沉到 dev 镜像脚本；host 侧单行命令（`mkdir`/`find`/`env`，见
  [ssh.py](file:///Users/x/workspace/devspace/controller/ssh.py)）保持内联，不引入额外下发机制。

## Part 1 — 配置收敛与改名

### 1.1 config.py 模型

新增两个模型并替换 `Config` 字段：

```python
class WorkspaceDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: NonBlankString                                            # 原 default_image
    container: ContainerConfig = Field(default_factory=ContainerConfig)  # 原全局 container

class WorkspacesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    defaults: WorkspaceDefaults
    items: dict[str, WorkspaceConfig]                                # 原 projects map
```

- `Config`：删除 `default_image`、`container`；`projects` → `workspaces: WorkspacesConfig`。顶层剩
  `hosts / workspaces / deployments / tokens / secrets`。`frozen=True` / `extra="forbid"` 不变（嵌套模型只读）。
- 重命名 `_BaseProject`/`RepoProject`/`GitProject`/`BlankProject`/`_normalize_project`/`ProjectConfig`/
  `ProjectHost` → `Workspace*` / `_normalize_workspace` / `WorkspaceConfig` / `WorkspaceHost`。
- `_validate_projects` → `_validate_workspaces`：遍历 `self.workspaces.items`，非空校验从 `Config` 移入此处。
- `resolved_container`：base 改为 `self.workspaces.defaults.container`。
- **`resolved_deployment_container`：去掉全局层**，改为从空 `ContainerConfig()` 起，依次并 `hosts[host].container`
  → `deployment.container`（deployment 不再继承开发默认值，这是本次核心收益）。
- `project_image/open_path/clone_path/ports` → `workspace_*`；`workspace_image` 读
  `self.workspaces.defaults.image`。`environment_spec` 参数 `project_id`→`workspace_id`，源 `self.workspaces.items`。
- `_validate_deployments`、`deployment_*`、`DeploymentConfig` 形状不变。
- `_merge_layer` / `_load_layers` / `load_config` **无需改动**：base 带 `workspaces.defaults` + `deployments`，
  私有 extend 带 `workspaces.items` + `hosts` + `tokens` + `secrets`，两侧 `workspaces` 均为 dict，按键深合并成
  `{defaults, items}`；已验证。

### 1.2 其余 Python 站点（改名，值不变）

- [models.py](file:///Users/x/workspace/devspace/controller/models.py)：`EnvironmentSpec.project_id`→`workspace_id`、
  `.project: ProjectConfig`→`.workspace: WorkspaceConfig`；`Environment.project`/`DashboardEnvironment.project`/
  `Operation.project` → `workspace`；`ProjectSummary`/`ProjectSummaryHost` → `WorkspaceSummary`/`WorkspaceSummaryHost`；
  `DashboardResponse.projects` → `workspaces`。`environment_labels` 改写 `LABEL_WORKSPACE`
  （`codespace.workspace`），源 `spec.workspace_id`；`MANDATORY_LABELS` 用 `LABEL_WORKSPACE`。
- [inventory.py](file:///Users/x/workspace/devspace/controller/inventory.py)：局部 `project`→`workspace`；
  `config.projects`→`config.workspaces.items`；`Environment(workspace=...)`。label 读取不变。
- [dashboard.py](file:///Users/x/workspace/devspace/controller/dashboard.py)、
  [operations.py](file:///Users/x/workspace/devspace/controller/operations.py)、
  [service.py](file:///Users/x/workspace/devspace/controller/service.py)、
  [api.py](file:///Users/x/workspace/devspace/controller/api.py)：随之改名（路由、字段、参数、`_project`→`_workspace`）。
  operation store 的 key 元组 `(host, workspace, instance)` 语义不变。
- [tools/cleanup_deploy_keys.py](file:///Users/x/workspace/devspace/controller/tools/cleanup_deploy_keys.py)
  `config.projects.items()` → `config.workspaces.items.items()`；
  [tools/cleanup_workspaces.py](file:///Users/x/workspace/devspace/controller/tools/cleanup_workspaces.py)
  `config.default_image` → `config.workspaces.defaults.image`。
- [static/app.js](file:///Users/x/workspace/devspace/controller/static/app.js) /
  [index.html](file:///Users/x/workspace/devspace/controller/static/index.html)：4 处 fetch URL `/api/projects/`→
  `/api/workspaces/`；JSON 字段 `item.project`→`item.workspace`、`dashboard.projects`→`dashboard.workspaces`；
  `#projects` 元素 id、"Projects" 标题等用户可见文案更新。CSS class 名同步更名（非承重）。

### 1.3 config.yaml

- 顶层重排为 `workspaces.defaults.{image, container}` + `deployments`（base 仍是不独立校验的片段）。
- **删除** `llm-vllm` / `llm-sglang` 里 `cap_add: []`、`security_opt: []`、`ulimits: {}` 这三行反向清除
  （deployment 不再继承开发默认值，自然为空）。
- **给 `deployments.sidecar.container` 显式加 `network_mode`**（如 `host`）——它原来靠全局默认，去掉全局层后
  必须显式声明，否则 `_validate_deployments` fail-fast。macOS podman-machine host 仍靠 `hosts.<host>.container`
  覆盖为 `bridge`，该层保留，解析正确。
- 私有 entrypoint（`~/devspace/config.extend.yaml`）：`projects:` → `workspaces.items:`，`extends:` 保留。

## Part 2 — 去硬编码 / 命令下沉

### 2.1 新增 dev 镜像脚本 `images/dev/rootfs/opt/codespace/bin/`

经 Dockerfile 现有 `COPY images/dev/rootfs/ /` 烤入（`/opt` 已 `chown 5230:5230`）。脚本 `0755`，
`#!/usr/bin/env bash` + `set -euo pipefail`，以用户 `x` 由控制面按绝对路径调用。镜像内已有 `git`/`jq`（binman）。

1. **`git-checkout <clone_url> <target>`**（替代 `_clone_url`）：完整保留语义——复用有效 checkout
   （`.git` + `rev-parse --verify HEAD`）、空仓库标记 `codespace-empty-repository` 复用、非 checkout 目录报错、
   `mkdir -p` 父目录、`rm -rf <target>.codespace-clone`、`git clone --depth=1`、空仓库 `touch` 标记、`mv` 到位。
   marker 字符串与错误文案保持逐字一致。
2. **`git-state <target>`**（替代 `checkout_git_state`/`_git_lines`）：输出 JSON
   `{"unpushed": bool, "uncommitted": bool, "detail": [...]}`（`jq -n` 保证转义），无 `.git` 输出全 false / 空。
   `detail` 取 dirty + unpushed 前 20 行。
3. **`prepare-open-path <path>`**（替代 `prepare_open_path`）：`mkdir -p -- "$path"`。

在 Dockerfile s6 setup 步骤旁补一句 `chmod -R +x /opt/codespace/bin`（保险，防 git 未保留可执行位）。

### 2.2 workspace.py 变薄

- `clone_repo`/`clone_git_url` → `execute_checked(container, ["/opt/codespace/bin/git-checkout", url, target], user=CONTAINER_USER, timeout=_CLONE_TIMEOUT)`。
- `checkout_git_state` → `execute` 调 `git-state`，非 0 抛错，`RepoGitState.model_validate_json(result.stdout)`。
- `prepare_open_path` → `execute_checked` 调 `prepare-open-path`。
- 删除 `_clone_url`、`_git_lines`、`_EMPTY_REPOSITORY_MARKER`。`repo_git_state`/`git_url_git_state` 仍为
  `checkout_git_state` 薄封装。

### 2.3 container.py 合并重复

提取私有 `_build_run_options(*, name, container, environment, ports, labels, mounts, secret_mounts, secret_env,
restart_policy=None)`，产出两者共享的 run_options（network_mode、cap_add、security_opt、ulimits、environment、
devices、ports、labels、mounts，以及条件 pids_limit/shm_size/ipc/secrets/secret_env）。`create_container` 保留
`platform` 与 `SSHD_*`/保留挂载专属逻辑；`create_deployment_container` 保留 `restart_policy` 与
`${DEPLOYMENT_DATA}` 占位符解析。只共享 dict 组装，不合并各自特有前置逻辑。

## Part 3 — 测试与文档

- **测试**：`conftest.py` 的 `config` fixture 重构为 `workspaces.defaults`+`items`；
  `test_config_models.py`（全部 `model_validate` 输入重排 + `workspace_image` 断言 +
  **新增** deployment 不再继承全局 caps、environment 仍继承的对照用例 + `workspaces` 深合并用例）；
  `test_runtime.py` 的 clone/git-state 测试改为断言单入口 `/opt/codespace/bin/git-checkout` 调用并 stub
  `git-state` stdout JSON 覆盖解析（bash 分支逻辑改为镜像内运行，Python 单测不再覆盖，属预期覆盖迁移）；
  `test_service.py`/`test_app.py`/`test_operations.py`/`test_compose_models.py` 及各 tools 测试同步改名。
- **文档**：`config.yaml`（见 1.3）；[controller/AGENTS.md](file:///Users/x/workspace/devspace/controller/AGENTS.md)
  的「配置」整节（顶层键、YAML 示例、必填键、override 分层须说明 deployment 只 `host→deployment`、API 路由）；
  根 [AGENTS.md](file:///Users/x/workspace/devspace/AGENTS.md) 契约 #9/#10/#11 的 project→workspace 术语；
  [images/dev/AGENTS.md](file:///Users/x/workspace/devspace/images/dev/AGENTS.md) 记录新 `/opt/codespace/bin/` 脚本；
  [images/llm/AGENTS.md](file:///Users/x/workspace/devspace/images/llm/AGENTS.md) 与
  [images/sidecar/AGENTS.md](file:///Users/x/workspace/devspace/images/sidecar/AGENTS.md) 说明 deployment 不再需要
  清除开发默认值、sidecar 需显式声明 `network_mode`。

## 风险

- **改名彻底、无迁移**：历史数据已清空、从零开始，故 label 值 `codespace.workspace`、`environment_id` 与宿主
  目录布局一并改齐；不存在需要兼容的存活容器或旧宿主目录，无迁移风险。
- **deployment 分层回归**：去全局层后 sidecar 必须显式 `network_mode`（1.3 已处理），否则 load 期 fail-fast。
- **脚本可执行位 / PATH**：`execute` 发送 `Env: None`，依赖镜像 `ENV PATH` 解析 `git`/`jq`；committed 脚本
  `0755` + Dockerfile `chmod -R +x` 兜底。
- **git 逻辑单测覆盖迁移**：clone/state 分支逻辑移入镜像 bash，Python 单测不再覆盖；靠保持 marker/文案逐字一致
  与文档标注缓解。

## 验证

在仓库根依次执行（Taskfile 已收纳）：

```bash
uv run ruff format --check controller
uv run ruff check controller
uv run mypy controller
uv run pytest controller/tests
uv lock --check
```

补充人工核对：`grep -rn "config.projects\|default_image\|config.container\b\|/api/projects" controller` 应无残留；
`bash -n images/dev/rootfs/opt/codespace/bin/*` 语法自检；对照阅读 `config.yaml` 确认 deployment 块已去除清除样板、
sidecar 已显式 `network_mode`。
