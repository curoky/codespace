---
name: rewrite-git-history
description: "安全规划并执行破坏性的 Git 历史重写：评估并清除已删除的无价值路径，合并连续的修正型提交，并把提交日期重排为指定时区与时间范围内自然、稀疏的开发节奏。仅在用户明确要求改写既有历史时使用；不用于普通 rebase、日常提交整理或未经授权的远端强推。"
---

# Rewrite Git History

用于用户明确要求清理、压缩、重新定时既有 Git 历史的场景。目标不是把历史机械压平，而是在不改变最终源码 tree 的前提下，留下可解释、可审计且看起来像真实开发 session 的线性历史。

这是破坏性操作。先完成审计与仓库外备份，在 disposable clone 中演练；默认只替换本地目标分支，**不得把“允许重写”推断成“允许 force-push”**。发布到远端前必须再次取得用户明确授权。

## Preconditions

1. 读取目标仓库的 `AGENTS.md` 和适用的子目录说明。
2. 确认目标分支、时间范围、时区，以及是否允许清理路径和 squash。缺失但可安全推断时采用保守值；影响 merge、tag、多人作者或签名时必须询问。
3. 审计并记录：

   ```bash
   git status --short --branch
   git remote -v
   git branch -avv
   git tag --list
   git rev-list --count <branch>
   git rev-list --merges --count <branch>
   git rev-list --max-parents=0 --count <branch>
   git log --format='%an <%ae>' <branch> | sort -u
   git log --format='%G?' <branch> | sort | uniq -c
   git rev-parse <branch>
   git rev-parse <branch>^{tree}
   ```

4. 若存在 tracked 工作区改动，停止并请用户处理；不得用 `reset --hard`、stash 或 checkout 擅自覆盖。列出 untracked 文件并保证全过程不删除它们。
5. 若历史有 merge、多个 root、tag 指向待重写提交、多个作者或有效签名，先说明将如何处理。不得默认线性化 merge、移动 tag、改写作者或丢弃签名。
6. 在仓库外创建可恢复备份，并实际验证：

   ```bash
   git bundle create /absolute/outside/repo-before-rewrite.bundle --all
   git bundle verify /absolute/outside/repo-before-rewrite.bundle
   ```

报告备份路径。不要把备份放入待重写仓库。

## 清理已删除路径

先生成“历史存在、当前分支已不存在”的候选，不得把全部候选直接删除：

```bash
comm -23 \
  <(git log <branch> --pretty=format: --name-only | sed '/^$/d' | sort -u) \
  <(git ls-tree -r --name-only <branch> | sort)
```

逐项查看 `git log --all -- <path>`、内容、体积和后继位置。只有同时满足以下条件才从所有历史清除：

- 当前 tip 已不存在；
- 是一次性生成物、误提交、缓存、临时实验、已被完全取代且无长期解释价值的旧文档/旧 workflow；
- 不承担 rename/migration 的重要前史；
- 用户没有要求保留；
- 不是需要按 incident-response 流程处理的 secret。发现凭据时先停止并告知用户轮换，不能把历史清理说成已经撤销泄漏。

保留已迁移实现、架构演进、关键 patch、发布协议和仍能解释当前设计的旧路径。仓库很小时，优先可读性而非追求无意义的字节减少。

在 disposable clone 中使用 `git filter-repo --invert-paths --paths-from-file ...`。路径清理后确认目标 tip tree 与原 tree 相同；若不同，候选列表有误，不得继续。

## 合并提交

只 squash 高置信度的相邻提交：

- 同一实现后数小时或同一开发 session 内的直接修复；
- 同一文件/同一目标的连续配置调试；
- add → immediate fix、rename → wiring fix、实现 → 格式清理；
- 完整升级后立即回退且净 tree 无变化时，可一起移除。

不要仅因提交“小”就合并。不同功能、不同 package、独立文档决策、独立测试或可单独回滚的修复应保留。先输出候选组及理由供审阅，再执行。优先保留组内首个能概括最终意图的 Conventional Commit message；若首条不再准确，重写为能解释整个净变化的 message。

使用 interactive rebase 时注意 todo 常用短 SHA，匹配脚本不能假定完整 SHA。fixup 因路径清理而变为空时可跳过，但完成后必须重新核对提交数和最终 tree。

## 重排为自然开发节奏

日期重排必须同时修改 author date 与 committer date，保留作者身份、提交 message、提交次序及每个保留节点的 tree。禁止仅把提交均匀铺到每一天——那会制造明显的机械模式。

默认节奏：

- 全部日期位于用户指定时区的允许工作日；本任务类型通常限制周六/周日；
- 约每 3–5 个提交组成一个活跃日，单日通常 2–5 个、上限 7 个；
- 活跃周末组成 1–4 周的小 burst，中间留 1–5 周空档，偶尔更长；
- 通常一个周末只工作一天，少量连续周六/周日；
- 日内为一段自然 session，提交间隔不规则，不把时间排成固定网格；
- 三年范围应整体覆盖，但不强迫首尾刚好贴边，也不要求每月都有提交；
- 使用固定 seed 保证可复现，并在报告中披露时间是合成重排的。

线性、无签名历史可使用 [`scripts/rewrite_dates_in_clone.sh`](scripts/rewrite_dates_in_clone.sh)：它只创建并改写新的 clone，不修改源仓库。
helper 依赖 GNU `date`；先加载平台工具环境，确认 `date -d` 可用，不使用 macOS 的 BSD `date`。

```bash
scripts/rewrite_dates_in_clone.sh \
  --repo /path/to/repo \
  --output /tmp/repo-history-dates \
  --branch master \
  --start 2023-09-21 \
  --end 2026-09-21 \
  --timezone +0800 \
  --seed 27491
```

脚本会拒绝 dirty tracked tree、merge、多个 root、tag 和签名提交。先审阅它输出的 active-day 与 commits-per-day 统计；节奏太密、太规律或与项目规模不符时换 seed 或显式调整 `--active-days`，不要硬接受默认结果。

## 验证

在临时仓库至少验证：

```bash
git fsck --full --no-dangling
git rev-list --count <branch>
git rev-list --merges --count <branch>
git rev-list --max-parents=0 --count <branch>
git rev-parse <branch>^{tree}
git diff --exit-code <original-tip> <rewritten-tip>
```

额外验证：

- 当前 tracked 文件数和最终 tree 与重写前一致；
- 被清理路径在目标分支全历史中不可达；
- author/committer 日期相等、时区正确、都落在允许工作日；
- 时间严格递增；
- 统计 active days、active weeks、每活跃日提交数 histogram、最长空档、每年分布；
- 不存在无意新增的 empty commit、merge 或 root；
- `git diff <old-tip> <new-tip>` 为空。

最终 tree 完全相同时，无需把未运行的构建或测试表述为通过；说明代码内容未变，因此只做了 Git 对象与历史不变量验证。

## 应用与发布

临时结果验证通过后，用 fetch 引入单独 ref，再以 compare-and-swap 方式更新本地分支：

```bash
old_local=$(git rev-parse <branch>)
git fetch --no-tags /tmp/rewrite-repo <branch>:refs/heads/history-rewrite
git update-ref refs/heads/<branch> refs/heads/history-rewrite "$old_local"
git reset --hard <branch>   # 仅限之前已确认 tracked tree clean
git branch -D history-rewrite
```

保留原远端 tip 作为 lease。默认停在本地并报告 `[ahead N, behind M]` 是历史替换后的预期。只有用户在看到验证摘要后明确授权发布，才执行：

```bash
git push --force-with-lease=refs/heads/<branch>:"$old_remote" origin <branch>
```

若 lease 失败，停止并重新审计远端；绝不改用裸 `--force`。不自动移动或重建 tag，不自动删除备份。

## Final Report

简洁报告：旧/新 tip、旧/新提交数、清理的路径类别与数量、squash 数量、日期范围/时区、活跃日和节奏统计、最终 tree 是否相同、`git fsck` 结果、备份位置、是否已推送。明确提醒协作者需要重新 clone 或 rebase 到新历史。

不要把合成日期包装成真实审计证据；此 skill 不适用于法律、合规、取证或安全事件时间线。
