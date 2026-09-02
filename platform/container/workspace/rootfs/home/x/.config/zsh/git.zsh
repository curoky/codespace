alias fixup='git commit -v --no-verify --fixup'

function git-unshallow() {
  git fetch --tags
  git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
  git fetch --unshallow
}

function git-history-files() {
  git log --pretty=format: --name-only --diff-filter=A | sort -u
}

function git-history-files-big() {
  local limit="${1:-10}"
  git rev-list --objects --all |
    git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' |
    awk '/^blob/ {print substr($0,6)}' |
    sort --numeric-sort --key=2 --reverse |
    head -n "$limit" |
    cut --complement --characters=13-40 |
    numfmt --field=2 --to=iec-i --suffix=B --padding=7 --round=nearest
}

function git-gc() {
  git for-each-ref --format="delete %(refname)" refs/original | git update-ref --stdin
  git reflog expire --expire=now --all
  git gc --prune=now
}

function git-submodule-upgrade() {
  local default_branch
  default_branch="$(git symbolic-ref refs/remotes/origin/HEAD)"
  default_branch="${default_branch#refs/remotes/origin/}"
  git submodule foreach "
    git reset --hard &&
    git checkout '$default_branch' &&
    git fetch --all &&
    git reset --hard 'origin/$default_branch' &&
    git pull
  "
}

function git-date-list() {
  git --no-pager log --pretty=format:"%ci"
}

function git-make-time-equal() {
  git filter-branch --env-filter 'export GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"' -f
}

function autosquash() {
  GIT_SEQUENCE_EDITOR=: git rebase --autosquash -i "$(git rev-list --max-parents=0 HEAD)"
  git-make-time-equal
}

function absorb() {
  git absorb --base "$(git rev-list --max-parents=0 HEAD)" "$@"
}

function wip() {
  git commit -v -m wip --no-verify
}

function commit() {
  git commit -v -m "$(date --rfc-3339=seconds)" "$@"
}

function git-show-deleted-files() {
  git log --diff-filter=D --summary | grep delete
}

function git-merge-repo() {
  if (( $# != 1 )); then
    print -u2 "usage: git-merge-repo URL"
    return 2
  fi

  git remote add prj "$1"
  git fetch prj --tags
  git merge --allow-unrelated-histories prj/master
  git remote remove prj
}
