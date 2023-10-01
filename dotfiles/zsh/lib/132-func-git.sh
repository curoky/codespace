# Copyright (c) 2018-2025 curoky(cccuroky@gmail.com).
#
# This file is part of devspace.
# See https://github.com/curoky/devspace for further info.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

alias fixup='git commit -v --no-verify --fixup'

function git-unshallow() {
  git fetch --tags
  git config remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'
  git fetch --unshallow
}

function git-history-files() {
  # https://stackoverflow.com/questions/543346/list-all-the-files-that-ever-existed-in-a-git-repository
  git log --pretty=format: --name-only --diff-filter=A | sort -u
}

function git-history-files-big() {
  limit=${1:-10}
  # old method
  # git rev-list --objects --all |
  #   grep "$(git verify-pack -v .git/objects/pack/*.idx | sort -k 3 -n | tail -20 | awk '{print$1}')"

  # new method
  # https://stackoverflow.com/questions/9456550/how-to-find-the-n-largest-files-in-a-git-repository/28783843
  # https://stackoverflow.com/questions/298314/find-files-in-git-repo-over-x-megabytes-that-dont-exist-in-head
  git rev-list --objects --all |
    git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' |
    awk '/^blob/ {print substr($0,6)}' |
    sort --numeric-sort --key=2 --reverse |
    head -n $limit |
    cut --complement --characters=13-40 |
    numfmt --field=2 --to=iec-i --suffix=B --padding=7 --round=nearest
}

function git-gc() {
  # do this after remove big files

  # rm -rf .git/refs/original/
  # git push origin --force --all
  git for-each-ref --format="delete %(refname)" refs/original | git update-ref --stdin
  git reflog expire --expire=now --all
  git gc --prune=now
}

function git-submodule-upgrade() {
  git submodule foreach "
        git reset --hard
        git checkout $(git symbolic-ref refs/remotes/origin/HEAD | sed 's@^refs/remotes/origin/@@') &&
        git fetch --all && git reset --hard origin/master && git pull"
}

function git-date-list() {
  git --no-pager log --pretty=format:"%ci"
}

function git-make-time-equal() {
  git filter-branch --env-filter 'export GIT_COMMITTER_DATE="$GIT_AUTHOR_DATE"' -f
}

function autosquash() {
  # https://stackoverflow.com/questions/29094595/git-interactive-rebase-without-opening-the-editor
  GIT_SEQUENCE_EDITOR=: git rebase --autosquash -i "$(git rev-list --max-parents=0 HEAD)"
  git-make-time-equal
}

function absorb() {
  # --and-rebase
  git absorb --base "$(git rev-list --max-parents=0 HEAD)" "$@"
}

function wip() {
  git commit -v -m 'wip' --no-verify
}

function commit() {
  git commit -v -m "$(date --rfc-3339=seconds)" "$@"
}

function git-show-deleted-files() {
  git log --diff-filter=D --summary | grep delete
}

function set-git-proxy() {
  export GIT_SSH=~/devspace/tools/git-proxy-wrapper.sh
  echo "export GIT_SSH=$GIT_SSH"
}

function git-merge-repo() {
  git remote add prj $1
  git fetch prj --tags
  git merge --allow-unrelated-histories prj/master
  git remote remove prj
}
