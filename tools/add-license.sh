#!/usr/bin/env bash
set -xeu

if [[ ! -d $PWD/.git ]]; then
  echo "must run in git root path"
  exit 1
fi

GitURL=$(git ls-remote --get-url | sed -e 's|git@github.com:|https://github.com/|' -e 's|\.git||')
FirstCommitYear=$(git log --reverse --date="format:%Y" --format="format:%ad" | head -n 1)
CurrentYear=$(date +'%Y')
Owner="$(git config user.name)($(git config user.email))"

licenseheaders \
  --tmpl=$HOME/devspace/dotfiles/licenseheaders/apache-2.tmpl \
  --owner=$Owner \
  --projname=$(basename "$PWD") \
  --projurl=$GitURL \
  --settings=$HOME/devspace/dotfiles/licenseheaders/license-settings.json \
  --exclude '*.yaml' '.md' '*.gzip.sh' '*.zstd.sh' \
  --dir ${1:-.} \
  --years="$FirstCommitYear-$CurrentYear"
