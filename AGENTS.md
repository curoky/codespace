# Codespace

Codespace 是个人开发环境的声明式控制面。macOS 是唯一 client，Linux 是唯一受管 remote
Host；控制面通过本机 OpenSSH 管理 Host 上的 rootful Podman。

## System Boundaries

- **Project** 是配置蓝图；**Workspace** 是其在指定 Host 上的命名实例，拥有持久数据、
  SSH 入口和可选 repository checkout。
- **Service** 是 Host 级单例，由配置声明 image、placement 和 container inputs。
- **WSL** 从 Workspace filesystem 派生本地 distribution，不属于受管 Host。
- 配置表达 desired state，Podman labels 与 inspect 表达 actual state；不以当前配置补齐
  已部署 metadata，不自动迁移过时资源。
- 依赖方向是 `web -> control -> workspaces/services -> runtime`。Web 不拥有业务状态，
  runtime 不读取应用配置，container artifact 不包含控制面逻辑。

## Context Index

按任务加载；下层 `AGENTS.md` 继承本文件，只补充自身约束。

| 任务 | 先读 | 联动上下文 |
| --- | --- | --- |
| 控制面、Web、Runtime、Maintenance 或 CLI | `src/codespace/AGENTS.md` | Agent 协议变化读 `platform/container/workspace/agent/AGENTS.md` |
| Workspace image、resource、rootfs 或 s6 | `platform/container/workspace/AGENTS.md` | 对应 Agent 或 tool 的下层文档 |
| Service image | `platform/container/services/AGENTS.md` | 共享 s6 变化同时读 Workspace 文档 |
| ASR | `platform/container/services/asr/AGENTS.md` | 部署读 `deployment/AGENTS.md`；语料和评分读 `regression/AGENTS.md` |
| Framework image | `platform/container/frameworks/AGENTS.md` | 对应 combo 的 Dockerfile 与 build script |
| macOS 环境、dotfiles 或 client SSH | `platform/macos/AGENTS.md` | 共享 home 变化同时读 Workspace 文档 |
| WSL build、boot 或 Windows wiring | `platform/wsl/AGENTS.md` | 继承的 filesystem/s6 变化同时读 Workspace 文档 |
| Codex LLMBox provider | `platform/container/workspace/tools/codex-llmbox-provider/AGENTS.md` | Go CLI；rootfs 提供配置模板 |

## Processing Contracts

- 同类资源写操作共用 identity、互斥和错误记录：先校验输入、ownership、凭据与最终 spec，
  再准备 image/data，最后修改资源。失败保留现场，不伪装成功或自动 rollback。
- 异步子任务属于发起它的请求或操作；失败/取消时先终止并等待关联任务，再清理文件。
  线程不会随协程取消而停止，仍使用文件的线程必须完成后才能释放文件。
- 自管 archive 安装统一为 checksum 校验、staging 解包、layout/executable 校验、发布、
  EXIT 清理。准备失败不破坏现有安装；原生 package manager 使用自身维护机制。
- 只抽取语义相同且有明确 owner 的基础能力，不因外观相似合并独立业务算法；不增加
  `common`、`utils`、compatibility package、fallback 或迁移层。

## Repository Rules

- 跨模块边界和上下文索引只写在根文档；模块文档使用 `Scope`、`Contracts`、
  `Pitfalls`、`Validation` 按需组织，不重复继承规则。不新增 `DESIGN.md` 或 `README.md`。
- 文档只保留职责、核心诉求、不变量、外部限制及验证入口。常见陷阱写明触发条件、影响和
  处理方式，限制消除后删除；测试不能代替约束原因。行为变化同步最近的文档。
- schema、manifest、代码、测试与 `Taskfile.yaml` 是可变细节的 source of truth；不复制
  版本、端口、目录树、完整清单或执行流程，不记录改造计划。测量与基线来源保存为数据产物，
  注明日期和口径，不把历史结果当成当前验证。
- 注释只解释代码无法表达的约束或外部兼容原因。Shell 使用 `#!/usr/bin/env bash`。
- 不修改无关用户、工作树或远端状态；真实 token、secret 与机器配置不得提交。
- 当前用户目录使用 `$HOME`、`~` 或 home API；固定用户 `x` 的初始化、rootfs、
  跨 stage COPY 和 mount 合同使用固定绝对路径。不用带用户名的 tilde 或额外账户查询。
  应用字段只在确认原生支持时使用路径展开，不增加模板替换或 Shell wrapper。
- 自管 SDK/runtime 与语言 CLI 放在 `$HOME/.local/opt`，macOS 与 Workspace 相对布局一致；
  应用数据、cache 与 package manager 保持原生布局。

## Validation

- 各 Go module 的 golangci-lint 共用系统临时目录中的进程锁；并行检查必须等待锁后串行
  执行，避免耗时超过工具默认的锁等待窗口而失败。
- 小风险改动只做直接相关的必要检查，不要求完整测试或 artifact 构建。
- 文档或非行为变更运行 `task check`；行为变更运行 `task check:full`。用户明确排除某模块
  验证时，执行其余检查并报告范围，不运行包含被排除模块的聚合任务。
- artifact 行为变化另按所属文档构建、export 或做平台验证；通用检查不能替代 artifact 验证。
  容器环境构建和运行使用 `/opt/podman/bin/podman`，context 为 repository root。
