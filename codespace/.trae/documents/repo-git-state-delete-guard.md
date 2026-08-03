# 计划：删除 repo 实例前检测未 push / 未提交并二次确认

## Summary

为 `type == "repo"` 的项目在**删除时**动态检测容器内仓库是否存在：

1. 未 push 的提交（本地领先远端）；
2. 未提交/未跟踪的改动（working tree 脏）。

采用**服务端拦截 + 前端二次确认**：`service.delete()` 在无 `force` 标记时，若检测到上述任一情况，`raise` 一个携带结构化详情的 409 错误；WebUI 弹窗展示具体状态，用户确认后带 `force=true` 重发请求。`blank` 项目无 checkout，跳过检测。

检测**只发生在删除路径**，dashboard 轮询不变，不给每次 1.5s 轮询增加 per-container git exec 开销（符合降复杂度/降开销偏好）。

## Current State Analysis

- 删除入口：[`service.py`](file:///Users/x/workspace/devspace/codespace/client/service.py#L293-L345) `CodespaceService.delete(project_id, instance, *, purge)`。已有严格的 mutation 顺序契约：先 revoke，再 purge，再 remove。checks 必须在任何 mutation 之前。测试 `test_delete_revokes_before_container_and_workspace_mutation` / `test_delete_revoke_failure_refuses_all_mutation` 守护此顺序。
- 删除 API：[`app.py`](file:///Users/x/workspace/devspace/codespace/client/app.py#L119-L137) `delete_instance`，已有 `purge: bool` query 参数；`Exception -> 409`。
- 容器内执行 git 的原语：[`runtime.py`](file:///Users/x/workspace/devspace/codespace/client/runtime.py#L403-L408) `_exec_checked`（丢弃 stdout）与 [`clone_repo`](file:///Users/x/workspace/devspace/codespace/client/runtime.py#L332-L345)（`container.exec_run([...], user=CONTAINER_USER)` 模板）。捕获 stdout 需直接调用 `container.exec_run`。
- 仓库 checkout 路径：[`models.py`](file:///Users/x/workspace/devspace/codespace/client/models.py#L136-L139) `repo_target(repo)` = `/workspace/<name>`。检测须用它，而非可被覆盖的 `open_path`。
- 容器句柄：[`runtime.py`](file:///Users/x/workspace/devspace/codespace/client/runtime.py#L190) `find_container(...)`（`delete()` 已获取 `container`）。
- WebUI 删除确认：[`app.js`](file:///Users/x/workspace/devspace/codespace/client/static/app.js#L199-L212) `deleteInstance(project, instance, purge)`，当前用静态 `window.confirm`。
- 错误归一化：API 异常处理器把错误转成 `{"error": "..."}`；[`app.js`](file:///Users/x/workspace/devspace/codespace/client/static/app.js#L29) `api()` 抛出 `error.message`。
- 契约文档：`codespace/CLAUDE.md` 的「Web 契约」「环境生命周期」；delete API 变更需同步更新。

## Proposed Changes

### 1. `runtime.py` — 新增容器内 git 状态检测

新增函数 `repo_git_state(container, repo) -> RepoGitState`（放在 `clone_repo` 附近）：

- `target = repo_target(repo)`。
- 先确认存在 checkout：`container.exec_run(["test", "-d", f"{target}/.git"], user=CONTAINER_USER)`；若不存在（exit != 0），返回“clean/无仓库”的空状态（不阻止删除）。
- 未提交/未跟踪：`container.exec_run(["git", "-C", target, "status", "--porcelain"], user=CONTAINER_USER)`；stdout 非空 => `dirty=True`，保留前若干行作为 `detail`。
- 未 push：`container.exec_run(["git", "-C", target, "log", "--branches", "--not", "--remotes", "--oneline"], user=CONTAINER_USER)`；stdout 非空 => `unpushed=True`，保留输出行作 `detail`。此命令覆盖所有本地分支相对所有 remote 的领先提交，无需依赖某个 upstream 设置，且无远端网络访问（读本地 refs）。
- 只调用 `exec_run` 直接拿 `(exit_code, bytes)` 并 decode；对 git 命令的**非零退出**（如损坏仓库）按 fail-fast 显式 `raise RuntimeError`，不静默吞掉（符合用户对 silent error 的反对）。

返回一个小的结构（可用 `models.py` 里的 pydantic model 或本文件内 dataclass；见第 2 项，统一放 models）。

### 2. `models.py` — 新增 `RepoGitState` 模型

新增：

```python
class RepoGitState(BaseModel):
    """容器内仓库的删除前安全检查结果。"""
    unpushed: bool = False
    uncommitted: bool = False
    detail: list[str] = Field(default_factory=list)

    @property
    def blocks_delete(self) -> bool:
        return self.unpushed or self.uncommitted
```

`runtime.repo_git_state` 返回该类型；`service.delete` 消费其 `blocks_delete` 与 `detail`。

### 3. `service.py` — 删除前拦截

修改 [`delete()`](file:///Users/x/workspace/devspace/codespace/client/service.py#L293) 签名为 `delete(self, project_id, instance, *, purge, force=False)`。

在获取 `container`（L313-L321）之后、**任何 mutation（revoke/purge/remove）之前**插入：

```python
if is_repo and not force:
    state = runtime.repo_git_state(container, self._require_repo(project))
    if state.blocks_delete:
        raise RepoDirtyError(identity, state)
```

- 新增异常类 `RepoDirtyError(RuntimeError)`，携带 `state`，其 `__str__` 给出人类可读摘要（用于 409 message 兜底），并暴露 `state` 供 API 序列化结构化详情。
- 顺序保证：检测在 revoke 之前，因此不违反“checks 通过前不 mutation”契约；`force=True` 时完全跳过检测，行为与今日一致。

### 4. `app.py` — delete 端点增加 `force` 参数并结构化 409

修改 [`delete_instance`](file:///Users/x/workspace/devspace/codespace/client/app.py#L119)：

- 增加 `force: Annotated[bool, Query()] = False`，透传给 `service.delete(..., force=force)`。
- 捕获 `RepoDirtyError`，返回 **409** 且 body 携带结构化字段，供前端渲染，例如：

```python
except RepoDirtyError as exc:
    raise HTTPException(status_code=409, detail={
        "error": str(exc),
        "code": "repo_dirty",
        "unpushed": exc.state.unpushed,
        "uncommitted": exc.state.uncommitted,
        "detail": exc.state.detail,
    })
```

保留既有 `KeyError->404` 与通用 `Exception->409`（`RepoDirtyError` 的 except 需放在通用 `Exception` 之前）。返回体保持 `{"ok": True, "workspace_removed": purge}` 不变。

> 注：这是对现有 delete 端点新增可选 query 参数，不新增端点；仍需同步更新 `codespace/CLAUDE.md`（见第 6 项）。

### 5. `static/app.js` — 二次确认弹窗

修改 [`deleteInstance`](file:///Users/x/workspace/devspace/codespace/client/static/app.js#L199)：

- 第一次仍走普通 `window.confirm`（保留现有轻确认），随后不带 `force` 发送 DELETE。
- 捕获 409 且 `code === "repo_dirty"` 的响应：不再当作普通错误 `notify`，而是弹出**第二次确认**，文案展示 `unpushed`/`uncommitted` 与 `detail`（前几行 git 输出），提示“存在未 push 提交 / 未提交改动，仍要删除吗？”。
- 用户确认后，带 `force=true` 重发 DELETE；成功则 `notify` + `refresh()`。
- 需要 `api()` 能拿到 409 的结构化 body：调整 `api()`（[app.js L29](file:///Users/x/workspace/devspace/codespace/client/static/app.js#L29)）在抛错时附带解析后的 JSON（如 `error.body = json`），供 `deleteInstance` 判定 `code`。保持对其它错误路径的兼容（仍有 `message`）。

无需改 CSS；复用现有 `notify`/`window.confirm`（符合“克制、用原生”偏好）。

### 6. 文档：`codespace/CLAUDE.md`

在「Web 契约 / 环境生命周期」相应位置补充：

- delete API 新增 `force` query 参数语义；
- repo 项目删除前进行未 push / 未提交检测，脏时返回 409 `repo_dirty`，需 `force=true` 覆盖；
- 检测只在删除路径发生，dashboard 不变。

（按用户规则：改动 API/生命周期须同步 `codespace/CLAUDE.md`。此为实现步骤之一，实现前会先提议确认文档措辞。）

## Assumptions & Decisions

- **时机**：只在删除时检测（用户已确认）。dashboard、`DashboardEnvironment` 不改动，避免每次轮询 per-container git exec 开销。
- **确认方式**：服务端拦截 + 前端二次确认（用户已确认）。服务端做真正的 fail-safe，前端负责展示详情与 `force` 重发。
- **未 push 判定**用 `git log --branches --not --remotes`，覆盖全部本地分支且纯本地读 refs，不做远端网络请求（快速、无需凭证）。
- **blank 项目**不检测（无 checkout）。
- **`force=true` 完全跳过检测**，保持与今日删除行为一致，且不破坏既有 mutation 顺序契约测试。
- **git 命令非零退出**显式 `raise`，不静默。
- 不新增 API 端点，仅给现有 delete 端点加可选 `force` 参数（贴合 CLAUDE.md API 约束）。

## Verification

新增/更新单测（`tests/`，用 `FakeContainer.exec_run` mock，参考 [`test_runtime.py`](file:///Users/x/workspace/devspace/codespace/client/tests/test_runtime.py) L66 与 [`test_service.py`](file:///Users/x/workspace/devspace/codespace/client/tests/test_service.py) L486/L514）：

- `runtime.repo_git_state`：clean / 仅 uncommitted / 仅 unpushed / 两者 / 无 `.git` / git 非零退出（raise）。
- `service.delete`：repo 脏 + `force=False` => `RepoDirtyError` 且**未发生任何 mutation**（复用现有顺序断言）；`force=True` => 正常删除；clean => 正常删除；blank => 不检测直接删除。
- `app` 层：脏删除返回 409 且 body 含 `code=repo_dirty` 与详情；`force=true` 走通。

命令（按 CLAUDE.md 验证节）：

```bash
uv run ruff format --check codespace/client
uv run ruff check codespace/client
uv run mypy codespace/client
uv run pytest codespace/client/tests
```

前端手动验证：对有未 push/未提交的 repo 实例点删除 -> 第一次确认后收到 409 -> 第二次弹窗展示详情 -> 确认后 `force` 删除成功。
