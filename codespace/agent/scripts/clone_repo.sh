#!/bin/sh
# Clone the main repository into the workspace, leaving an existing checkout
# untouched. Run via `sh -c <script> clone-repo <git_host> <repo> <target>`
# from codespace.agent.credentials, so the positional args are:
#   $1  git_host  provider ssh host (e.g. github.com)
#   $2  repo      owner/name repo path
#   $3  target    absolute clone destination under /workspace
set -eu
git_host="$1"
repo="$2"
target="$3"
if [ -d "$target/.git" ]; then
  exit 0
fi
if [ -e "$target" ]; then
  echo "target already exists and is not a git repository: $target" >&2
  exit 1
fi
git clone "git@$git_host:$repo.git" "$target"
