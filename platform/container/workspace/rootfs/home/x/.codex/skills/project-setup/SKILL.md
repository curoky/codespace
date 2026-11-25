---
name: "project-setup"
description: "从零搭建项目与工程治理的跨语言约定：项目结构与目录组织、配置与环境管理、统一工具链（包管理/lint/格式/类型/测试/构建/git hook）、语言与工具版本基线、Git 提交接线、语义化版本（SemVer）、变更日志（changelog）、依赖治理、CI/CD 流水线。当用户搭建新项目、初始化脚手架、配置工具链、锁定版本、发版或治理依赖时调用。"
---

# 工程化（项目结构 · 工具链 · 版本与协作）

> 从零搭项目、配工具链、发版与治理依赖时加载。本 skill 只讲**跨语言原则**；各语言的具体工具/命令、配置与锁文件名、pre-commit 命令、库选型与版本基线，是 `../refactor/languages/{lang}.md`（js/python/go/cpp/swift/bash）的基线（§0）、工具链节与库选型表——那里是唯一真相，本文件不重复枚举。
>
> **重构既有代码**见 `refactor` skill；**提交信息怎么写**见 `git-commit-message` rule/skill。

## 1. 项目结构与组织

**核心原则**：按功能组织，目录可预测、职责单一、入口清晰。

- **标准目录布局**：源码放 `src/`、脚本放 `scripts/`、文档放 `docs/`，配置文件放仓库根；测试就近或集中，团队内统一其一。各语言的具体布局约定（Go 的 `cmd/`/`internal/`、C++ 的 `include/` + `BUILD.bazel` 等）见对应 `../refactor/languages/{lang}.md`。
- **按功能分模块**：优先按业务领域/功能切分目录，而非 controllers/services/utils 等技术层大杂烩；避免 `util`/`common`/`base` 等无意义包与 `utils.h` 大杂烩。
- **单包 vs monorepo**：单一职责项目用单包；多个可独立发布的包用 monorepo（具体 workspace 机制见各语言规范）。
- **文件职责单一**：一个文件聚焦一个模块/类/功能；过大（经验值数百行）即按职责拆分。
- **入口清晰**：明确唯一入口，对外 API 通过入口、包导出或公共接口统一暴露。

## 2. 配置与环境管理

**核心原则**：配置集中声明、启动即校验、按环境注入；代码不散落读取裸环境变量。

- **配置集中且校验**：所有配置集中定义并在启动时校验，失败立即 fail-fast；具体校验库见各语言库选型表（如配置/校验一栏）。
- **分层来源**：优先级「默认值 < 配置文件 < 环境变量」；多环境通过环境变量切换，不在代码里散落 `if env === 'prod'` 判断。
- **`.env` 约定**：本地用 `.env`（不提交），仓库提供 `.env.example` 列出所有必填项与说明。
- **必填与默认**：明确区分必填项（缺失即报错）与可选项（有合理默认值）；类型在 Schema / struct tag 中声明。
- **配置不可变**：启动后配置视为只读，集中通过一个 typed config 对象访问，不在各处直接读裸环境变量。

## 3. 统一工具链（跨语言）

**核心原则**：用统一现代的工具链，配置入库，本地与 CI 复用配置和脚本入口，按反馈时延分层执行、结果可复现。

- **工具选型偏好**：优先选速度快、配置少、能合并多职责的工具（如一体化 Lint + 格式化）；各语言具体工具见 `../refactor/languages/{lang}.md` 的工具链节。
- **配置与锁文件入库**：项目的配置文件与锁文件必须提交，保证依赖可复现；具体文件名见各语言规范。
- **git hook 统一用 `lefthook` 管理**：`lefthook.yml` 入库，支持并行执行与暂存文件过滤（`{staged_files}` + `glob`），替代 `husky`/`lint-staged`/`pre-commit` 框架/Makefile；`pre-commit` 只跑可按暂存文件执行的 format/lint 等秒级检查，`pre-push` 可按项目规模运行类型检查和测试，`commit-msg` 挂 `commitlint`（见 §5）。
- **完整检查可一键运行**：提供一个项目级命令串起格式校验、Lint/静态分析、类型检查/vet、测试与构建；本地可主动运行，CI 强制执行。
- **复用入口而非强求同一范围**：pre-commit、pre-push、CI 调用同一组底层脚本和配置，但按耗时与检查粒度取子集；项目级类型检查、测试、构建与漏洞扫描不得伪装成 staged-file 检查。

## 4. 语言与工具版本基线

**核心原则**：新项目默认用官方最新稳定且生态兼容的版本，避免 EOL 与预发布版；落地前查官方发布页重新核实，并在配置中精确锁定。存量项目按既有兼容边界升级，不静默改版本。

- **精确锁定**：兼容范围用于发布声明，开发/CI runtime 与工具链锁到具体 patch；各语言具体锁定方式（版本文件、`toolchain` 指令、hermetic toolchain 等）见 `../refactor/languages/{lang}.md` 的基线（§0）。
- **升级判据**：最新版本若缺少关键 API 或生态支持，记录具体阻塞、官方来源与临时版本；阻塞解除后由 Renovate 或定期审计恢复到最新稳定版。

## 5. 提交规范（接线）

**核心原则**：提交遵循 Conventional Commits，使历史可读、可机器解析，并驱动版本与 changelog。提交信息「怎么写」的完整格式见 `git-commit-message` rule/skill；本节只讲工具接线。

- 用 `commitlint` 强制校验（在 `lefthook.yml` 的 `commit-msg` 钩子中挂载）；交互式提交可用 `commitizen`。
- 提交历史由 Conventional Commits 驱动版本推导（§6）与 changelog 自动生成（§7）。

## 6. 语义化版本（SemVer）

**核心原则**：版本号遵循 SemVer 2.0.0：`MAJOR.MINOR.PATCH`。

- **MAJOR** 破坏性变更、**MINOR** 向后兼容新功能、**PATCH** 向后兼容修复；预发布用 `-alpha`/`-beta`/`-rc`。
- **由 Conventional Commits 自动推导**：`feat` → minor、`fix` → patch、`!`/`BREAKING CHANGE` → major；不手动随意 bump。
- 版本号唯一来源并与 Git tag（`vX.Y.Z`）一致：JS 看 `package.json`、Python 看 `pyproject.toml`、Go 直接以 Git tag 为准（无独立版本文件）。
- **Go 模块版本特殊约定**：major 版本 ≥ 2 时，模块路径须带 `/vN` 后缀（如 `example.com/foo/v2`）并对应 `vN.x.x` tag，否则下游无法正确升级。

## 7. 变更日志（Changelog）

**核心原则**：维护面向使用者的 `CHANGELOG.md`，遵循 Keep a Changelog。

- 按版本分组，分类列出 `Added`/`Changed`/`Fixed`/`Deprecated`/`Removed`/`Security` 并标注日期。
- 由 Conventional Commits **自动生成**：JS/TS 用 `changesets`（推荐，适合 monorepo）或 `release-please`；Python 用 `towncrier` 或 `git-cliff`。
- 破坏性变更须显著标注并说明迁移方式。

## 8. 依赖治理

**核心原则**：依赖**可复现、可追溯、可审计**；锁定版本、定期升级、主动扫漏洞。

- **首次引入先核实**：从官方 registry / release 获取最新稳定兼容版，检查支持的 runtime、最近发布、归档/停维状态、安全公告与许可证；已归档、明确停维或仅有预发布版的库不得作为新项目默认。
- **例外要留依据**：因框架 peer dependency、平台或迁移成本不能用最新稳定版时，在 PR/设计记录中写明阻塞和升级条件，不凭模型记忆选择旧版本。
- **锁文件必须提交**：所有语言的锁文件必须入库，CI 用 frozen/locked 模式校验一致性、禁静默更新；各语言具体锁文件名与校验命令见 `../refactor/languages/{lang}.md`。
- **版本约束清晰**：直接依赖声明明确范围，运行版本以锁文件为准。

**自动升级**：

- **工具**：统一用 Renovate（跨生态）；纯 GitHub 仓库可用 Dependabot；配置入库。
- **调度**：每周固定窗口批量提 PR（`schedule`），设并发上限（`prConcurrentLimit`）避免 PR 风暴。
- **分级合并**：`patch`/`devDependencies` CI 通过后自动合并；生产 `minor` 至少 1 人评审；`major`/破坏性必须人工评审 + 迁移说明 + 回归。
- **聚合降噪**：非主要版本按生态分组（`groupName`）；锁文件维护（`lockFileMaintenance`）每周单独跑。
- **安全升级优先**：开启 `vulnerabilityAlerts`，安全补丁不受调度限制第一时间提 PR。
- **质量门禁**：所有升级 PR 必须 CI 全绿（含自动合并）才可合并。

**安全审计**：

- **CI 强制扫描**：每次 PR 与主分支扫漏洞，达阈值即阻断；各语言具体扫描工具（`pnpm audit`、`pip-audit`、`govulncheck`、`osv-scanner` 等）见 `../refactor/languages/{lang}.md`。
- **阻断阈值**：`high` 及以上（CVSS ≥ 7.0）须修复或显式豁免；`moderate` 及以下记录跟踪。
- **修复 SLA**：`critical` 24h、`high` 7d、`moderate` 30d 内处理。
- **豁免机制**：无法立即修复时登记白名单，注明原因/责任人/复审日期，并经评审。
- **供应链加固**：CI 用最小权限 token；锁文件保证可复现；定期生成 SBOM（如 CycloneDX）。
- **依赖精简**：定期清理未使用依赖（各语言工具见 `../refactor/languages/{lang}.md`）；引入新依赖前对照对应语言「库选型」的选型判据。
- **许可证合规**：避免引入与项目协议冲突的依赖（如 GPL 进闭源），必要时用工具校验。

## 9. CI/CD 流水线

**核心原则**：CI 检查与本地一致、快速反馈、全绿才合并；发布自动化、可复现。

- **必跑检查清单**：安装（锁文件校验）→ 格式校验 → Lint → 类型检查/`go vet` → 测试（带覆盖率，Go 加 `-race`）→ 构建 → 漏洞扫描；任一失败即阻断。
- **与本地一致**：CI 调用本地可一键运行的完整检查入口；pre-commit 只取其中适合暂存文件的快速子集（见 §3）。
- **快速反馈**：拆分并行任务、用缓存缩短时长；快检查（Lint/类型）前置。
- **发布自动化**：合并主分支后由 Conventional Commits 驱动版本与 changelog（`changesets`/`release-please`/`towncrier`），自动打 tag 并发布。
- **最小权限与可复现**：CI 凭据最小权限，安装用 `--frozen-lockfile`/`--locked`。
- **分支保护**：主分支要求 PR + CI 全绿 + 至少 1 人评审，禁止直接推送。
