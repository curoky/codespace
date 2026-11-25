#!/usr/bin/env bats

setup_file() {
  bats_require_minimum_version 1.5.0
}

setup() {
  MACOS_DIR="$(cd "$BATS_TEST_DIRNAME/.." && pwd -P)"
  WORKSPACE_HOME="$(cd "$MACOS_DIR/../container/workspace/rootfs/home/x" && pwd -P)"
  TEST_ROOT="$(mktemp -d)"
  HOME="$TEST_ROOT/home"
  export HOME
  mkdir -p "$HOME"
}

teardown() {
  rm -rf "$TEST_ROOT"
}

@test "shared collaboration rules agree across platforms and tools" {
  local workspace="$WORKSPACE_HOME/.codex/AGENTS.md"
  local macos="$MACOS_DIR/rootfs/Users/x/.codex/AGENTS.md"
  local trae="$WORKSPACE_HOME/.trae/user_rules/ai-collaboration.md"

  grep -q '^## Engineering Principles$' "$workspace"
  grep -q '^## Engineering Principles$' "$macos"
  grep -q '^alwaysApply: true$' "$trae"
  grep -q '^## Engineering Principles$' "$trae"
  diff <(sed -n '/^## Engineering Principles$/,$p' "$workspace") \
    <(sed -n '/^## Engineering Principles$/,$p' "$macos")
  diff <(sed -n '/^## Engineering Principles$/,$p' "$workspace") \
    <(sed -n '/^## Engineering Principles$/,$p' "$trae")
}

@test "each platform environment rule agrees across Codex and Trae" {
  local platform codex trae
  for platform in Container macOS; do
    if [[ "$platform" == Container ]]; then
      codex="$WORKSPACE_HOME/.codex/AGENTS.md"
      trae="$WORKSPACE_HOME/.trae/user_rules/container-environment.md"
    else
      codex="$MACOS_DIR/rootfs/Users/x/.codex/AGENTS.md"
      trae="$MACOS_DIR/rootfs/Users/x/.trae/user_rules/macos-environment.md"
    fi
    grep -q "^## $platform Environment$" "$codex"
    grep -q "^# $platform Environment$" "$trae"
    grep -q '^alwaysApply: true$' "$trae"
    diff <(sed -n "/^## $platform Environment$/,/^## Engineering Principles$/{
        /^## /d
        /^$/d
        p
      }" "$codex") \
      <(sed -n "/^# $platform Environment\$/,\$p" "$trae" | sed '1d; /^$/d')
  done
}

@test "Git commit rule and skill have the same writing contract" {
  local codex="$WORKSPACE_HOME/.codex/skills/git-commit-message/SKILL.md"
  local trae="$WORKSPACE_HOME/.trae/user_rules/git-commit-message.md"
  grep -q '^scene: git_message$' "$trae"
  grep -q '^生成提交内容' "$codex"
  grep -q '^生成提交内容' "$trae"
  diff <(sed -n '/^生成提交内容/,$p' "$codex") \
    <(sed -n '/^生成提交内容/,$p' "$trae")
}

@test "Workspace packages complete skills and relative Trae links" {
  local skill editor language rule
  for skill in git-commit-message project-setup refactor rewrite-git-history; do
    [ -f "$WORKSPACE_HOME/.codex/skills/$skill/SKILL.md" ]
    grep -Eq "^name: \"?$skill\"?$" "$WORKSPACE_HOME/.codex/skills/$skill/SKILL.md"
  done
  for editor in .trae .trae-cn; do
    for skill in project-setup refactor; do
      [ "$(readlink "$WORKSPACE_HOME/$editor/skills/$skill")" = "../../.codex/skills/$skill" ]
      [ "$WORKSPACE_HOME/$editor/skills/$skill" -ef "$WORKSPACE_HOME/.codex/skills/$skill" ]
      for language in js python go cpp swift bash; do
        [ -f "$WORKSPACE_HOME/$editor/skills/refactor/languages/$language.md" ]
        [ -f "$WORKSPACE_HOME/$editor/skills/project-setup/../refactor/languages/$language.md" ]
      done
    done
  done
  for rule in ai-collaboration git-commit-message container-environment; do
    [ "$(readlink "$WORKSPACE_HOME/.trae-cn/user_rules/$rule.md")" = "../../.trae/user_rules/$rule.md" ]
    [ "$WORKSPACE_HOME/.trae-cn/user_rules/$rule.md" -ef "$WORKSPACE_HOME/.trae/user_rules/$rule.md" ]
  done
  [ -x "$WORKSPACE_HOME/.codex/skills/rewrite-git-history/scripts/rewrite_dates_in_clone.sh" ]
  run grep -n 'agent-playbook' "$MACOS_DIR/../container/workspace/Dockerfile"
  [ "$status" -eq 1 ]
}

@test "macOS links shared AI assets without installing container skills" {
  run "$MACOS_DIR/maintenance/home-links.sh"
  [ "$status" -eq 0 ]

  local skill editor rule language
  for skill in git-commit-message project-setup refactor rewrite-git-history; do
    [ -L "$HOME/.codex/skills/$skill" ]
    [ "$HOME/.codex/skills/$skill" -ef "$WORKSPACE_HOME/.codex/skills/$skill" ]
  done
  for editor in .trae .trae-cn; do
    for skill in project-setup refactor; do
      [ -L "$HOME/$editor/skills/$skill" ]
      [ "$HOME/$editor/skills/$skill" -ef "$WORKSPACE_HOME/.codex/skills/$skill" ]
      for language in js python go cpp swift bash; do
        [ -f "$HOME/$editor/skills/project-setup/../refactor/languages/$language.md" ]
      done
    done
    for rule in ai-collaboration git-commit-message; do
      [ "$HOME/$editor/user_rules/$rule.md" -ef "$WORKSPACE_HOME/.trae/user_rules/$rule.md" ]
    done
    [ "$HOME/$editor/user_rules/macos-environment.md" -ef \
      "$MACOS_DIR/rootfs/Users/x/.trae/user_rules/macos-environment.md" ]
    [ ! -e "$HOME/$editor/user_rules/container-environment.md" ]
  done
  for editor in .codex .trae .trae-cn; do
    [ ! -e "$HOME/$editor/skills/debug-github" ]
    [ ! -e "$HOME/$editor/skills/manage-services" ]
  done
  run "$HOME/.codex/skills/rewrite-git-history/scripts/rewrite_dates_in_clone.sh" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *'Source Git repository (never modified)'* ]]
}

@test "AI home links converge per entry and preserve unrelated assets" {
  local editor
  for editor in .codex .trae .trae-cn; do
    mkdir -p "$HOME/$editor/skills/.system" "$HOME/$editor/skills/user-installed" \
      "$HOME/$editor/skills/refactor"
    printf 'system\n' >"$HOME/$editor/skills/.system/keep"
    printf 'user\n' >"$HOME/$editor/skills/user-installed/keep"
    printf 'stale\n' >"$HOME/$editor/skills/refactor/stale"
  done
  for editor in .trae .trae-cn; do
    mkdir -p "$HOME/$editor/user_rules" "$HOME/$editor/rules"
    printf 'custom\n' >"$HOME/$editor/user_rules/custom.md"
    printf 'other\n' >"$HOME/$editor/rules/other.md"
  done

  run "$MACOS_DIR/maintenance/home-links.sh"
  [ "$status" -eq 0 ]
  run "$MACOS_DIR/maintenance/home-links.sh"
  [ "$status" -eq 0 ]
  for editor in .codex .trae .trae-cn; do
    [ ! -L "$HOME/$editor/skills" ]
    [ "$(<"$HOME/$editor/skills/.system/keep")" = system ]
    [ "$(<"$HOME/$editor/skills/user-installed/keep")" = user ]
    [ ! -e "$HOME/$editor/skills/refactor/stale" ]
  done
  for editor in .trae .trae-cn; do
    [ ! -L "$HOME/$editor/user_rules" ]
    [ "$(<"$HOME/$editor/user_rules/custom.md")" = custom ]
    [ "$(<"$HOME/$editor/rules/other.md")" = other ]
  done
}

@test "history helper rewrites only its disposable clone" {
  run date -d '2026-01-01 + 1 day' +%F
  if [[ "$status" -ne 0 ]]; then
    skip 'GNU date is required; native full-install CI repeats this test after binman'
  fi
  run "$MACOS_DIR/maintenance/home-links.sh"
  [ "$status" -eq 0 ]
  local source="$TEST_ROOT/source" rewritten="$TEST_ROOT/rewritten"
  git init --quiet --initial-branch=main "$source"
  git -C "$source" config user.name 'AI Test'
  git -C "$source" config user.email 'ai-test@example.invalid'
  local revision
  for revision in 1 2 3 4 5 6; do
    printf '%s\n' "$revision" >"$source/revision"
    git -C "$source" add revision
    GIT_AUTHOR_DATE='2025-01-01T00:00:00+0000' GIT_COMMITTER_DATE='2025-01-01T00:00:00+0000' \
      git -C "$source" -c commit.gpgsign=false commit --quiet -m "test(ai): revision $revision"
  done
  local tip tree helper
  tip="$(git -C "$source" rev-parse HEAD)"
  tree="$(git -C "$source" rev-parse 'HEAD^{tree}')"
  helper="$HOME/.codex/skills/rewrite-git-history/scripts/rewrite_dates_in_clone.sh"
  run "$helper" --repo "$source" --output "$rewritten" --branch main \
    --start 2026-01-01 --end 2026-01-31 --timezone +0800 --seed 27491 --active-days 2
  [ "$status" -eq 0 ]
  [ "$(git -C "$source" rev-parse HEAD)" = "$tip" ]
  [ -z "$(git -C "$source" status --porcelain)" ]
  [ "$(git -C "$rewritten" rev-parse 'HEAD^{tree}')" = "$tree" ]
  [ "$(git -C "$rewritten" rev-list --count HEAD)" -eq 6 ]
  [ "$(git -C "$rewritten" rev-parse HEAD)" != "$tip" ]
  diff <(git -C "$source" log --reverse --format='%T %an %ae %cn %ce %s') \
    <(git -C "$rewritten" log --reverse --format='%T %an %ae %cn %ce %s')
  git -C "$rewritten" log --reverse --format='%at %ct' |
    awk '$1 != $2 || (NR > 1 && $1 <= previous) { exit 1 } { previous = $1 }'
  local timestamp weekday
  while read -r timestamp; do
    [[ "$timestamp" == 2026-01-*+08:00 ]]
    weekday="$(date -d "$timestamp" +%u)"
    [[ "$weekday" == 6 || "$weekday" == 7 ]]
  done < <(git -C "$rewritten" log --format=%aI)

  run "$helper" --repo "$source" --output "$rewritten"
  [ "$status" -ne 0 ]
  [[ "$output" == *'output already exists'* ]]
  printf 'dirty\n' >"$source/revision"
  run "$helper" --repo "$source" --output "$TEST_ROOT/dirty-output"
  [ "$status" -ne 0 ]
  [[ "$output" == *'source repository has tracked changes'* ]]
  [ ! -e "$TEST_ROOT/dirty-output" ]
  [ "$(git -C "$source" rev-parse HEAD)" = "$tip" ]
  [ "$(<"$source/revision")" = dirty ]
}
